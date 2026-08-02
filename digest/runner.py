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
import threading

from PySide6.QtCore import QThread, Signal

from core import logs, settings
from core.logs import logger


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
        self._sink_id = logger.add(self._to_window, format="{message}", level="INFO")
        lock_taken = False
        digest = None
        try:
            try:
                # импорт здесь, а не наверху: digest.py при плохих настройках
                # завершает процесс с кодом 2, и в окне это убило бы программу
                import digest as digest_module
                digest = digest_module
            except SystemExit:
                self.failed.emit("Настройки не читаются — проверка не запускалась. "
                                 "Откройте «Настройки…» и проверьте их.")
                return
            except Exception as e:
                self.failed.emit(f"Не удалось подготовить проверку: {e}")
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

            summary = asyncio.run(digest.main(
                dry_run=self.dry_run, hours=self.hours,
                progress=self._on_progress, cancel=self._cancel))
        except Exception as e:
            logger.exception("Проверка упала")
            self.failed.emit(f"Проверка прервалась: {e}")
            return
        finally:
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
