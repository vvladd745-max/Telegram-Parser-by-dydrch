"""Главное окно дайджеста (PySide6).

Слева — разделы, справа — работа. Справа же видно, что программа о себе знает:
папка данных, вход в Telegram, каналы, модель, — и что не так с настройками.
Отсюда запускается прогон: в отдельном потоке, с прогрессом по каналам,
счётчиками и кнопкой остановки.

Отдельные экраны живут в своих файлах: settings_window, channels_window,
interests_window, wizard. Сам прогон — в runner. Оформление — в ui.

Запуск из исходников: python digest/app.py
"""
import sys, os
# Корень проекта в путь — чтобы работал импорт пакета core/ из любой папки.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portalocker
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QCheckBox, QMessageBox, QFrame, QStackedWidget,
)

from core import settings, paths, llm, logs, secrets
from tgclient import TelegramWorker
from wizard import LoginWizard
from settings_window import SettingsWindow
from channels_window import ChannelsWindow
from interests_window import InterestsWindow
from about import AboutPage
from runner import DigestRun
from console import RunConsole
import ui

APP_TITLE = "Парсер Telegram-каналов"

# как объяснить человеку выбор папки с данными (paths.mode())
MODE_TEXT = {
    "env": "задан вручную переменной DIGEST_HOME",
    "portable": "портативный — файлы лежат рядом с программой",
    "user": "обычный — файлы в папке пользователя",
}

# В боковой панели полное название не помещается, поэтому там короткий вариант,
# а на самой странице стоит полный заголовок.
NAV_RUN = "Проверка каналов"

PAGE_RUN, PAGE_SETTINGS, PAGE_CHANNELS, PAGE_INTERESTS, PAGE_LOGIN, PAGE_ABOUT = range(6)
PAGE_TITLES = {
    PAGE_RUN: "Проверка Telegram-каналов",
    PAGE_SETTINGS: "Настройки",
    PAGE_CHANNELS: "Каналы",
    PAGE_INTERESTS: "Интересы",
    PAGE_LOGIN: "Вход в Telegram",
    PAGE_ABOUT: "О программе",
}

CONSOLE_HINT = ("Здесь будет видно, что происходит во время проверки: "
                "какой канал читается и какое решение принято по каждому посту.")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        icon = ui.app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(940, 660)
        self.run = None      # текущая проверка, пока идёт
        self.restart_requested = False   # окно просит пересобрать себя

        # поток Telegram общий для всех страниц: клиент Telethon должен быть один
        self.telegram = TelegramWorker(parent=self)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_pages(), 1)

        self.telegram.logged_in.connect(
            lambda name: self.telegram_value.setText(f"выполнен — {name}"))
        self.telegram.logged_out.connect(
            lambda: self.telegram_value.setText("не выполнен"))
        self.telegram.status.connect(self.telegram_value.setText)
        self.telegram.failed.connect(self.telegram_value.setText)
        self.telegram.start()
        self.telegram.check()

        self.go_to(PAGE_RUN, force=True)
        self.refresh()
        self._look_at_start = self._look()

    @staticmethod
    def _look():
        """Настройки внешнего вида, ради которых окно приходится пересобирать."""
        return (settings.get("ui.theme", "system"), settings.get("ui.font_size", 0))

    # ---------- сборка окна ----------

    def _build_sidebar(self):
        side = QWidget()
        # ширина считается от шрифта: при крупных буквах фиксированные 216
        # точек обрезали пункты меню на середине слова
        metrics = QFontMetrics(self.font())
        widest = max(metrics.horizontalAdvance(text) for text in
                     (NAV_RUN, "Вход в Telegram", "Перечитать настройки",
                      "О программе", "✓ Готово к работе"))
        side.setFixedWidth(max(216, widest + 84))
        side.setObjectName("sidebar")
        side.setStyleSheet(
            f"#sidebar {{ background: {ui.color(self, 'panel')};"
            f" border-right: 1px solid {ui.color(self, 'line')}; }}")

        layout = QVBoxLayout(side)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        logo = ui.logo_label(self, size=28)
        if logo is not None:
            head.addWidget(logo, 0, Qt.AlignTop)
        head.addWidget(ui.label(APP_TITLE, size=14, bold=True, wrap=True), 1)
        layout.addLayout(head)
        layout.addWidget(ui.label("Отбор постов из Telegram", tone="muted",
                                  widget=self, wrap=True))
        layout.addSpacing(14)

        self.run_nav = ui.nav_button(self, NAV_RUN, active=True)
        self.settings_button = ui.nav_button(self, "Настройки")
        self.channels_button = ui.nav_button(self, "Каналы")
        self.interests_button = ui.nav_button(self, "Интересы")
        self.login_button = ui.nav_button(self, "Вход в Telegram")
        self.about_button = ui.nav_button(self, "О программе")
        self.nav_buttons = {
            PAGE_RUN: self.run_nav,
            PAGE_SETTINGS: self.settings_button,
            PAGE_CHANNELS: self.channels_button,
            PAGE_INTERESTS: self.interests_button,
            PAGE_LOGIN: self.login_button,
            PAGE_ABOUT: self.about_button,
        }
        for index, button in self.nav_buttons.items():
            button.clicked.connect(lambda _=False, i=index: self.go_to(i))
            layout.addWidget(button)

        layout.addStretch(1)
        self.health = ui.label("", tone="muted", widget=self, wrap=True)
        layout.addWidget(self.health)
        self.reload_button = ui.nav_button(self, "Перечитать настройки")
        self.reload_button.clicked.connect(self.refresh)
        layout.addWidget(self.reload_button)
        return side

    def _build_pages(self):
        """Все разделы — страницы одного окна. Всплывающих окон больше нет:
        человеку не приходится искать, какое из них сейчас главное."""
        self.pages = QStackedWidget()
        self.settings_page = SettingsWindow()
        self.channels_page = ChannelsWindow(self.telegram)
        self.interests_page = InterestsWindow()
        self.login_page = LoginWizard(self.telegram)
        self.about_page = AboutPage()
        self.page_widgets = {
            PAGE_SETTINGS: self.settings_page,
            PAGE_CHANNELS: self.channels_page,
            PAGE_INTERESTS: self.interests_page,
            PAGE_LOGIN: self.login_page,
            PAGE_ABOUT: self.about_page,
        }

        self.pages.insertWidget(PAGE_RUN, self._build_main())
        for index, page in self.page_widgets.items():
            self.pages.insertWidget(index, self._wrap(PAGE_TITLES[index], page))

        for page in (self.settings_page, self.channels_page, self.interests_page):
            page.saved.connect(self.on_page_saved)
            page.cancelled.connect(self.back_to_run)
        self.login_page.finished_login.connect(self.back_to_run)
        return self.pages

    def _wrap(self, title, page):
        """Заголовок раздела и единые отступы вокруг страницы."""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)
        layout.addWidget(ui.label(title, size=16, bold=True))
        if page.layout() is not None:
            page.layout().setContentsMargins(0, 0, 0, 0)
        layout.addWidget(page, 1)
        return box

    def back_to_run(self):
        self.go_to(PAGE_RUN, force=True)

    def go_to(self, index, force=False):
        """Переключение раздела. Уходя со страницы с несохранёнными правками,
        сначала спрашиваем: молча терять введённое нельзя."""
        current = self.pages.currentIndex()
        if current == index:
            return
        leaving = self.page_widgets.get(current)
        if not force and leaving is not None and getattr(leaving, "has_changes", bool)():
            answer = QMessageBox.question(
                self, "Есть несохранённые правки",
                "В разделе «" + PAGE_TITLES[current] + "» остались несохранённые "
                "изменения. Уйти и потерять их?")
            if answer != QMessageBox.Yes:
                return
        self.pages.setCurrentIndex(index)
        for number, button in self.nav_buttons.items():
            ui.set_nav_active(self, button, number == index)
        entering = self.page_widgets.get(index)
        if entering is not None and hasattr(entering, "page_show"):
            entering.page_show()

    def on_page_saved(self):
        # тема и размер букв «запекаются» в оформление при сборке окна,
        # поэтому окно надо собрать заново — иначе половина осталась бы старой
        if self._look() != self._look_at_start:
            self.restart_requested = True
            self.close()
            return
        self.refresh()
        # настройки могли поменять api_id и api_hash: старый клиент Telethon
        # держит прежние, поэтому отпускаем сессию и проверяем вход заново.
        # Иначе в состоянии висела бы ошибка, которую человек уже исправил.
        self.telegram.release_session()
        self._reconnect_telegram()
        self.back_to_run()

    def _build_main(self):
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        # --- заголовок и главное действие ---
        head = QHBoxLayout()
        head.addWidget(ui.label(PAGE_TITLES[PAGE_RUN], size=16, bold=True))
        head.addStretch(1)
        self.dry_run_box = QCheckBox("Тестовая проверка")
        self.dry_run_box.setChecked(True)
        self.dry_run_box.setToolTip(
            "Тестовая проверка ничего не пересылает и не двигает закладки по каналам: "
            "она только показывает, что программа отобрала бы.")
        self.cancel_button = ui.flat_button(self, "Остановить")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        self.cancel_button.setToolTip(
            "Проверка дочитает текущий пост и остановится. Отобранное уже отправлено, "
            "остальное дочитается в следующий раз.")
        self.run_button = ui.primary_button(self, "Запустить проверку")
        self.run_button.clicked.connect(self.start_run)
        head.addWidget(self.dry_run_box)
        head.addWidget(self.cancel_button)
        head.addWidget(self.run_button)
        layout.addLayout(head)

        # --- что программа о себе знает ---
        self.home_value = ui.label(selectable=True, wrap=True)
        self.mode_value = ui.label(wrap=True)
        self.settings_value = ui.label(selectable=True, wrap=True)
        self.channels_value = ui.label()
        self.model_value = ui.label(selectable=True, wrap=True)
        self.log_value = ui.label(selectable=True, wrap=True)
        self.telegram_value = ui.label("проверяю...", wrap=True)

        state = QGridLayout()
        state.setHorizontalSpacing(16)
        state.setVerticalSpacing(6)
        rows = (("Вход в Telegram", self.telegram_value),
                ("Каналов в списке", self.channels_value),
                ("Модель", self.model_value),
                ("Папка с данными", self.home_value),
                ("Режим", self.mode_value),
                ("Журнал", self.log_value))
        for i, (name, value) in enumerate(rows):
            state.addWidget(ui.label(name, tone="muted", widget=self), i, 0, Qt.AlignRight)
            state.addWidget(value, i, 1)
        state.setColumnStretch(1, 1)
        layout.addWidget(ui.card(self, "Состояние", state))

        # --- претензии к настройкам: карточка появляется, только если есть что сказать ---
        self.problems_value = ui.label(wrap=True, selectable=True)
        problems_layout = QVBoxLayout()
        problems_layout.addWidget(self.problems_value)
        self.problems_card = ui.card(self, "Что нужно поправить", problems_layout)
        layout.addWidget(self.problems_card)

        # --- прогон ---
        run_layout = QVBoxLayout()
        run_layout.setSpacing(8)
        self.progress_label = ui.label("", tone="muted", widget=self)
        self.progress = ui.thin_progress(self)
        self.progress_label.setVisible(False)
        self.progress.setVisible(False)
        run_layout.addWidget(self.progress_label)
        run_layout.addWidget(self.progress)

        counters = QHBoxLayout()
        counters.setSpacing(28)
        self.counter_labels = {}
        for key, name, tone in (("checked", "Проверено", "text"),
                                ("found", "Интересных", "ok"),
                                ("skipped", "Пропущено", "muted"),
                                ("errors", "Ошибок", "muted")):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            value = ui.label("0", size=15, bold=True, tone=tone, widget=self)
            cell.addWidget(value)
            cell.addWidget(ui.label(name, tone="muted", widget=self))
            counters.addLayout(cell)
            self.counter_labels[key] = value
        counters.addStretch(1)
        run_layout.addLayout(counters)

        self.console = RunConsole(self)
        self.console.set_hint(CONSOLE_HINT)
        run_layout.addWidget(self.console, 1)
        layout.addWidget(ui.card(self, "Проверка", run_layout), 1)

        self.status = ui.label("", wrap=True)
        layout.addWidget(self.status)
        return main

    # ---------- прогон ----------

    def start_run(self):
        if self.run is not None and self.run.isRunning():
            return
        # Проверять нечем — говорим об этом словами. Иначе Telethon вывалит
        # английскую трассировку про пустой API ID, и человек решит,
        # что программа сломана.
        troubles = settings.blockers()
        if troubles:
            self.status.setStyleSheet(f"color: {self._error_color()};")
            self.status.setText(
                "Проверку не запустить: " + troubles[0] +
                (f" (и ещё {len(troubles) - 1})" if len(troubles) > 1 else "") +
                ". Загляните в «Настройки».")
            return
        dry_run = self.dry_run_box.isChecked()
        if not dry_run:
            answer = QMessageBox.question(
                self, "Настоящая проверка",
                "Программа прочитает каналы и перешлёт отобранное. Закладки по каналам "
                "сдвинутся: те же посты второй раз уже не придут.\n\nЗапускать?")
            if answer != QMessageBox.Yes:
                return

        hours = int(settings.get("digest.dry_run_hours" if dry_run
                                 else "digest.lookback_hours") or 2)
        self.console.clear()
        # режим печати журнала берём на старте: менять его посреди проверки незачем
        self.console.set_matrix(bool(settings.get("ui.matrix", True)))
        self.progress_label.setVisible(True)
        self.progress_label.setText("Готовлюсь...")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)          # пока не знаем, сколько каналов
        self._set_counters()
        self._set_busy(True)
        self.status.setText("Тестовая проверка идёт..." if dry_run else "Проверка идёт...")
        # файл сессии Telegram один, и это база SQLite: пока её держит окно,
        # прогон не откроется вовсе. Отпускаем на время прогона.
        self.telegram.release_session()
        self.telegram_value.setText("сессию держит проверка")

        self.run = DigestRun(dry_run, hours, self)
        self.run.line.connect(self.console.append_line)
        self.run.step.connect(self.on_step)
        self.run.done.connect(self.on_run_done)
        self.run.failed.connect(self.on_run_failed)
        self.run.finished.connect(self.run.stop_logging)
        self.run.start()

    def cancel_run(self):
        if self.run is not None and self.run.isRunning():
            self.run.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Останавливаю: дочитываю текущий пост...")

    def on_step(self, data):
        event = data.get("event")
        if event == "start":
            self.progress.setRange(0, int(data.get("total") or 0))
            self.progress.setValue(0)
        elif event == "channel":
            self.progress.setValue(int(data.get("number") or 0))
            self.progress_label.setText(
                f"Канал {data.get('number', 0)} из {data.get('total', 0)} — "
                f"{data.get('name', '')}")
        elif event in ("counters", "done"):
            self._set_counters(data.get("checked", 0), data.get("found", 0),
                               data.get("skipped", 0), data.get("errors", 0))

    def _set_counters(self, checked=0, found=0, skipped=0, errors=0):
        for key, value in (("checked", checked), ("found", found),
                           ("skipped", skipped), ("errors", errors)):
            self.counter_labels[key].setText(str(value))

    def on_run_done(self, summary, stopped):
        self._set_busy(False)
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        # сначала перечитываем настройки, потом пишем итог: refresh ставит свою
        # строку состояния и иначе затирал бы сообщение о прогоне
        self.refresh()
        self._reconnect_telegram()
        if stopped:
            self.status.setText("Проверка остановлена. Недочитанное придёт в следующий раз.")
        else:
            self.status.setText("Проверка закончена.")

    def on_run_failed(self, text):
        self._set_busy(False)
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self._reconnect_telegram()
        self.status.setStyleSheet(f"color: {self._error_color()};")
        self.status.setText(text)

    def _reconnect_telegram(self):
        """Проверка закончилась и отпустила файл сессии — можно подключаться снова."""
        self.telegram_value.setText("проверяю...")
        self.telegram.check()

    def _set_busy(self, busy):
        """Во время проверки настройки не трогаем: она читает их на ходу."""
        self.run_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.dry_run_box.setEnabled(not busy)
        for button in (self.settings_button, self.channels_button,
                       self.interests_button, self.login_button, self.reload_button):
            button.setEnabled(not busy)
        if busy:
            self.go_to(PAGE_RUN, force=True)
        if not busy:
            self.status.setStyleSheet("")

    # ---------- экраны ----------

    def closeEvent(self, event):
        # идёт прогон — спрашиваем, а не обрываем молча
        if self.run is not None and self.run.isRunning():
            answer = QMessageBox.question(
                self, "Проверка ещё идёт",
                "Остановить проверку и закрыть программу? Уже отправленное останется, "
                "остальное дочитается в следующий раз.")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.run.cancel()
            self.run.wait(30000)
        # поток входа надо остановить, иначе процесс не завершится
        self.telegram.shutdown()
        super().closeEvent(event)

    def _error_color(self):
        """Цвет для списка проблем. Зависит от темы Windows: тёмно-красный
        читается на светлом фоне и почти сливается с тёмным."""
        return ui.color(self, "bad")

    def refresh(self):
        """Перечитывает настройки с диска и заполняет окно заново.

        Ошибка в настройках не должна ронять окно: человеку показывается
        строка о том, что случилось, а не пустой экран.
        """
        self.home_value.setText(paths.home())
        self.settings_value.setText(paths.settings_file())
        self.log_value.setText(paths.logs_dir())
        self.mode_value.setText(MODE_TEXT.get(paths.mode(), paths.mode()))

        url, name = llm.endpoint()
        self.model_value.setText(f"{name} · {url}")

        try:
            settings.load(force=True)
            self.channels_value.setText(str(len(settings.channels())))
            troubles = settings.problems()
        except settings.SettingsError as e:
            self.channels_value.setText("—")
            troubles = [str(e)]

        self.problems_card.setVisible(bool(troubles))
        if troubles:
            self.problems_value.setText("\n".join("• " + t for t in troubles))
            self.problems_value.setStyleSheet(f"color: {self._error_color()};")
            self.health.setText(f"⚠ Не хватает настроек: {len(troubles)}")
            self.health.setStyleSheet(f"color: {self._error_color()};")
            self.status.setText("Настройки надо поправить — смотрите список справа.")
        else:
            self.problems_value.setText("")
            self.health.setText("✓ Готово к работе")
            self.health.setStyleSheet(f"color: {ui.color(self, 'ok')};")
            self.status.setText("")


def take_app_lock():
    """Замок на всю программу. None — значит она уже запущена.

    Два окна разом работать не могут: файл сессии Telegram — это база SQLite,
    и второй экземпляр получает «database is locked», а человек видит
    непонятную английскую ругань в журнале.

    Замок держит операционная система, пока жив процесс: если программу
    убили или машина перезагрузилась, он снимается сам.
    """
    paths.ensure_dirs()
    try:
        handle = open(paths.app_lock_file(), "a+", encoding="utf-8")
    except OSError:
        return None                       # некуда писать — лучше запустить, чем не дать
    try:
        portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
    except portalocker.exceptions.BaseLockException:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def main():
    logs.setup("app")
    # Первое, что пишем в журнал: где мы и что нам доступно. В сборке без
    # консоли это единственный способ понять, почему у человека не работает.
    logs.logger.info(
        f"Запуск: сборка={paths.frozen()}, режим={paths.mode()}, "
        f"папка данных={paths.home()}, хранилище секретов={secrets.available()}")
    # первый запуск на чистой машине: раскладываем заготовки настроек,
    # чтобы окно показывало «заполните api_id», а не «файла нет»
    for created in settings.bootstrap():
        logs.logger.info(f"Создан файл настроек: {created}")
    # разовый переезд: секреты из settings.json в Диспетчер учётных данных Windows
    settings.migrate_secrets()
    app = QApplication(sys.argv)
    icon = ui.app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    lock = take_app_lock()
    if lock is None:
        logs.logger.warning("[!] Программа уже запущена — второе окно не открываю.")
        QMessageBox.information(
            None, APP_TITLE,
            "Программа уже запущена.\n\n"
            "Посмотрите на панели задач — окно там. Двум окнам разом работать "
            "нельзя: они начнут мешать друг другу читать Telegram.")
        return 0
    # Окно собирается заново, если человек сменил тему или размер букв:
    # эти вещи задаются при создании виджетов и на лету не переключаются.
    while True:
        ui.apply_theme(app, settings.get("ui.theme", "system"))
        ui.apply_base_font(app, settings.get("ui.font_size", 0))
        window = MainWindow()
        window.show()
        code = app.exec()
        if not window.restart_requested:
            return code
        settings.load(force=True)


if __name__ == "__main__":
    sys.exit(main())
