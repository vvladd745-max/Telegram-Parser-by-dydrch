"""Прогон дайджеста из окна: отдельный поток со своим циклом asyncio.

Почему так, а не иначе:
  - прогон идёт в потоке, чтобы окно не замирало на полчаса;
  - режим и глубина передаются в main() ЯВНО. В sys.argv у окна нет
    --dry-run, и прогон молча оказался бы боевым;
  - боевой прогон берёт тот же лок, что и запуск из командной строки, —
    иначе окно и расписание могли бы пойти одновременно и задвоить посты;
  - итоговый отчёт отправляется ПОСЛЕ закрытия цикла asyncio. Внутри цикла
    блокирующий requests подвешивал прогон намертво.
"""
import asyncio
import os
import sys
import threading

from PySide6.QtCore import QThread, Signal

from core import lastrun, logs, lmstudio, paths, settings
from core.logs import logger


def _topics_dir():
    """Где лежит личный инструмент поиска тем. Считается здесь и только здесь:
    путь нужен и прогону, и окну настроек.

    Ищем рядом с программой (paths.app_dir): в сборке это папка с .exe,
    из исходников — корень проекта. Внутрь сборки инструмент не запекается,
    он лежит обычной папкой снаружи — так его можно положить себе и не отдать
    коллегам вместе с установщиком."""
    return os.path.join(paths.app_dir(), "topic_finder")


def topics_available():
    """Есть ли рядом с программой поиск тем.

    По этому ответу окно решает, показывать ли галочку. У коллег инструмента
    нет — и галочки они не увидят вовсе, вместо того чтобы включать пустое
    место и потом искать, почему ничего не происходит."""
    return os.path.isfile(os.path.join(_topics_dir(), "topic_finder.py"))


class DigestRun(QThread):
    """Одна проверка. Второй раз объект не переиспользуется — создавайте новый."""

    line = Signal(str)          # строка журнала для окна
    step = Signal(dict)         # события хода работы из main()
    done = Signal(str, bool)    # (итоговый отчёт или "", остановлен ли кнопкой)
    failed = Signal(str)        # понятная человеку ошибка

    def __init__(self, dry_run, hours, parent=None):
        super().__init__(parent)
        self.dry_run = bool(dry_run)
        self.hours = int(hours)
        self._cancel = threading.Event()
        self._stopped = False
        self._sink_id = None

    def cancel(self):
        """Просьба остановиться. Проверка дочитает текущий пост и выйдет по
        чекпоинту: курсор останется на последнем успешно отправленном."""
        self._cancel.set()

    # ---------- поток ----------

    def run(self):
        # весь вывод прогона дублируем в окно
        # В окно — только сами сообщения. Трассировки остаются в файле журнала:
        # человеку они ничего не говорят, а экран забивают целиком.
        self._sink_id = logger.add(self._to_window, format="{message}", level="INFO",
                                   backtrace=False, diagnose=False,
                                   filter=lambda record: record["exception"] is None)
        lock_taken = False
        digest = None
        lms_done = None      # что мы подняли в LM Studio: это же и уберём
        try:
            try:
                # импорт здесь, а не наверху: digest.py при плохих настройках
                # завершает процесс с кодом 2, и в окне это убило бы программу
                import digest as digest_module
                digest = digest_module
            except SystemExit:
                self.failed.emit("Файл настроек не читается — проверка не начиналась. "
                                 "Загляните в раздел «Настройки»: там будет написано, "
                                 "что именно не так.")
                return
            except Exception as e:
                self.failed.emit(f"Не удалось подготовить проверку: {e}. "
                                 "Подробности — в журнале программы.")
                return

            # журнал проверки — всегда в один файл, и тестовой, и настоящей:
            # иначе половина записей уходила бы в журнал окна
            logs.setup("digest")
            if not self.dry_run:
                if not digest.acquire_lock():
                    self.failed.emit(
                        "Уже идёт другая проверка — эту не запускаю, чтобы не задвоить посты.")
                    return
                lock_taken = True

            # Отметка ставится ДО подъёма модели: оборвать могут и во время
            # загрузки, и тогда убирать за собой всё равно придётся.
            lastrun.started(self.dry_run)

            # Модель поднимаем и для тестовой проверки тоже: она точно так же
            # спрашивает у модели про каждый пост.
            try:
                lms_done = lmstudio.prepare()
            except lmstudio.LMStudioError as e:
                self.failed.emit(str(e))
                return
            lastrun.remember_lms(lms_done)
            if self._cancel.is_set():
                # успели нажать «Остановить», пока грузилась модель
                self.done.emit("", True)
                return

            summary = asyncio.run(digest.main(
                dry_run=self.dry_run, hours=self.hours,
                progress=self._on_progress, cancel=self._cancel))

            # Поиск тем — здесь, пока модель ещё в памяти: поднимать её второй раз
            # значило бы ждать лишние полминуты и занять гигабайты дважды.
            # Раньше это был шаг [5/6] в run_all.bat.
            if settings.get("digest.find_topics", False):
                if self._cancel.is_set():
                    logger.info("Остановлено — темы не ищу.")
                else:
                    self._find_topics()
        except ValueError as e:
            # Telethon так ругается на пустые api_id и api_hash
            logger.exception("Проверка упала")
            self.failed.emit("Проверка не началась: не заполнены api_id и api_hash. "
                             "Впишите их в разделе «Настройки» → «Доступ к Telegram». "
                             "Там же ссылка, где их выдают.")
            return
        except Exception as e:
            # Подробности с трассировкой — в журнал, человеку — одна строка
            logger.exception("Проверка упала")
            self.failed.emit(f"Проверка прервалась: {e}. "
                             "Отобранное до этого уже отправлено, остальное "
                             "дочитается в следующий раз. Подробности — в журнале.")
            return
        finally:
            # Память освобождаем в любом случае, даже если проверка упала:
            # иначе модель на несколько гигабайт останется висеть до
            # перезагрузки компьютера. Убираем только то, что подняли сами.
            lmstudio.release(lms_done)
            # Отметку снимаем последней и всегда: сюда мы попадаем и когда
            # проверка прошла, и когда упала, и когда её остановили кнопкой.
            # Во всех трёх случаях уборка отработала — доделывать нечего.
            lastrun.finished()
            if lock_taken and digest is not None:
                digest.release_lock()

        # отчёт боту — уже вне цикла asyncio, как и при запуске из командной строки.
        # Галочку «присылать отчёт» в настройках уважаем: иначе она ничего не значила бы.
        if summary and not self.dry_run and settings.get("bot.enabled", True):
            try:
                from core import telegram
                logger.info("Отправляю итог боту...")
                ok = telegram.send_message(summary)
                logger.info("Итог отправлен." if ok else "[!] Итог отправить не удалось.")
            except Exception as e:
                logger.warning(f"   [!] отчёт боту не ушёл: {e}")

        self.done.emit(summary or "", self._stopped)

    # ---------- поиск тем ----------

    def _find_topics(self):
        """Шаг после проверки постов: собрать темы для статей.

        Почему так:
          - импорт ленивый, как и у digest: без папки topic_finder программа
            должна работать как ни в чём не бывало, а не падать при старте;
          - зовём синхронно, прямо в этом потоке. Цикл asyncio уже закрыт,
            поэтому блокирующий requests внутри ничего не подвесит — по той же
            причине, по которой отчёт боту уходит отсюда же, а не из main();
          - своя обёртка try: упавший поиск тем не должен превращаться
            в «проверка прервалась». Посты к этому моменту уже разосланы.

        Кнопка «Остановить» поиск тем не прерывает: механизма остановки
        внутри topic_finder нет.
        """
        if not topics_available():
            logger.warning("   [!] поиск тем не найден рядом с программой — пропускаю.")
            return

        try:
            tf_dir = _topics_dir()
            if tf_dir not in sys.path:
                sys.path.insert(0, tf_dir)
            import topic_finder
            # Убеждаемся, что нашёлся именно наш модуль, и забираем нужное
            # ЗДЕСЬ, внутри try. Рядом может оказаться пустая папка с тем же
            # именем — Python отдаёт такую как пакет, и обращение к
            # topic_finder.TopicFinderError в строке except уронило бы сам
            # обработчик ошибок. Упавший except не ловится соседним except:
            # прогон завершился бы криком «проверка прервалась», хотя посты
            # к тому времени уже разосланы.
            run_topics = topic_finder.main
            TopicsError = topic_finder.TopicFinderError
        except Exception as e:
            logger.warning(f"   [!] поиск тем недоступен: {e}")
            return

        logger.info("Ищу темы для статей...")
        try:
            # Режим наследуем у проверки: тестовая проверка — тестовый поиск,
            # без отправки и без записи. Иначе правку было бы не проверить:
            # галочка «Тестовая проверка» стоит по умолчанию.
            run_topics(dry_run=self.dry_run)
        except TopicsError as e:
            # Ожидаемая беда, о которой есть что сказать словами
            logger.warning(f"   [!] темы не искались: {e}")
        except Exception as e:
            logger.exception("Поиск тем упал")
            logger.warning(f"   [!] поиск тем прервался: {e}. Подробности — в журнале.")

    # ---------- мостики в окно ----------

    def _to_window(self, message):
        self.line.emit(str(message).rstrip("\n"))

    def _on_progress(self, event, **data):
        if event == "done":
            self._stopped = bool(data.get("stopped"))
        data["event"] = event
        self.step.emit(data)

    def stop_logging(self):
        """Снять окно с потока журнала. Зовётся, когда проверка завершилась."""
        if self._sink_id is not None:
            try:
                logger.remove(self._sink_id)
            except ValueError:
                pass
            self._sink_id = None
