"""Окно входа в Telegram: ключи доступа, номер, код, пароль двухфакторной защиты.

Окно ничего не делает само — оно только показывает страницы и передаёт
введённое в рабочий поток (digest/tgclient.py), а обратно получает сигналы.
Поэтому оно не замирает, пока Telegram думает.

Почему api_id и api_hash появились здесь, хотя они есть в «Настройках».
Без них вход невозможен в принципе, а человек, открывший «Вход в Telegram»,
видел только поле для номера — и упирался в отказ, не понимая, куда идти.
Теперь они стоят там же, где нужны, и ровно до тех пор, пока нужны: после
входа страница показывает уже другое, и ключи с глаз убираются. В
«Настройках» они остаются — там их правят, когда всё уже работает.
"""
import ui
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QStackedWidget, QWidget,
    QCheckBox, QDialog, QLabel, QLineEdit, QPushButton, QMessageBox, QScrollArea,
)

from core import settings
from core.logs import logger

PAGE_PHONE, PAGE_CODE, PAGE_PASSWORD, PAGE_DONE = range(4)

KEYS_URL = "https://my.telegram.org"

ACCESS_TEXT = (
    "Это ключи вашего личного приложения Telegram: по ним программа читает "
    "каналы от вашего имени. Выдаются бесплатно и один раз. Если не знаете, "
    "где их взять, — нажмите кнопку выше, там всё расписано по шагам."
)

# Инструкция вынесена в отдельное окно, а не в подсказку под кругляшком:
# подсказка живёт, пока мышь висит над значком, а по этой инструкции человек
# ходит несколько минут, переключаясь между программой и браузером.
KEYS_HELP = """
<p>Программа читает каналы <b>от вашего имени</b>, как это делает обычный
Telegram на телефоне. Чтобы Telegram её пустил, нужны два кода — их выдают
бесплатно и один раз на всю жизнь.</p>

<p><b>Шаг 1.</b> Откройте <b>my.telegram.org</b> — кнопка внизу этого окна.</p>

<p><b>Шаг 2.</b> Введите номер телефона того аккаунта Telegram, который
подписан на нужные каналы. В международном виде, начиная с плюса:
<b>+79161234567</b>.</p>

<p><b>Шаг 3.</b> Код придёт <b>не в СМС</b>, а в само приложение Telegram —
в чат с названием «Telegram» и синей галочкой. Введите код на сайте.</p>

<p><b>Шаг 4.</b> На открывшейся странице выберите пункт
<b>API development tools</b>.</p>

<p><b>Шаг 5.</b> Заполните форму. Обязательных полей всего два:</p>
<ul>
<li><b>App title</b> — название, любое. Например: <b>digest</b></li>
<li><b>Short name</b> — короткое имя: только латинские буквы и цифры,
от 5 знаков. Например: <b>digest01</b></li>
<li><b>URL</b>, <b>Description</b> — можно оставить пустыми</li>
<li><b>Platform</b> — выберите <b>Desktop</b></li>
</ul>

<p><b>Шаг 6.</b> Нажмите <b>Create application</b>.</p>

<p><b>Шаг 7.</b> На той же странице появятся <b>App api_id</b> — число,
и <b>App api_hash</b> — длинная строка из букв и цифр. Их и впишите
в программу.</p>

<p>Создавать приложение нужно <b>один раз</b>. Если потеряли коды — просто
зайдите на my.telegram.org снова, они лежат на том же месте.</p>

<hr>

<p><b>Чужие ключи брать не стоит</b></p>

<p>Может показаться, что проще попросить коды у знакомого, который уже
всё настроил. Так делать не надо. Коды выдаются одному человеку под одно
приложение, и когда с одной парой начинают ходить десятки разных аккаунтов,
Telegram такие коды блокирует.</p>

<p>Сломается при этом не у одного, а <b>сразу у всех</b>, кто ими пользуется, —
включая того, кто их вам дал. Свои получить дольше, но надёжнее.</p>

<hr>

<p><b>Если сайт отвечает ошибкой</b></p>

<p>my.telegram.org капризный: он может ругаться, даже когда всё заполнено
правильно. Это не ваша вина и не поломка программы. Что обычно помогает:</p>
<ul>
<li>повторить попытку через несколько минут — чаще всего дело в этом;</li>
<li>открыть сайт в другом браузере или в приватном окне;</li>
<li>убрать из названий кириллицу, пробелы и знаки препинания — оставить
только латинские буквы и цифры;</li>
<li>если включён VPN — попробовать и с ним, и без него.</li>
</ul>

<p>Сайт принадлежит Telegram, и повлиять на него мы не можем. Но обычно
после одной-двух попыток форма проходит.</p>
"""


def show_keys_help(parent):
    """Окно с пошаговой инструкцией «где взять api_id и api_hash».

    Открывается по кнопке рядом с полями. Текст длинный и с прокруткой:
    человек читает его, переключаясь на браузер и обратно, поэтому окно
    немодальное по духу — но модальным его делает Qt, чтобы не потерялось
    за главным окном.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Где взять api_id и api_hash")
    dialog.setMinimumSize(560, 520)

    body = QLabel(KEYS_HELP)
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    body.setAlignment(Qt.AlignTop)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(body)
    scroll.setFrameShape(QScrollArea.NoFrame)

    open_button = QPushButton("Открыть my.telegram.org")
    open_button.setDefault(True)
    open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KEYS_URL)))
    close_button = QPushButton("Закрыть")
    close_button.clicked.connect(dialog.accept)

    row = QHBoxLayout()
    row.addWidget(open_button)
    row.addStretch(1)
    row.addWidget(close_button)

    layout = QVBoxLayout(dialog)
    layout.addWidget(scroll)
    layout.addLayout(row)
    dialog.exec()


def _page(title, hint, *widgets):
    """Страница визарда: заголовок, пояснение и содержимое."""
    page = QWidget()
    layout = QVBoxLayout(page)
    head = QLabel(title)
    head.setStyleSheet("font-size: 15px; font-weight: bold;")
    note = QLabel(hint)
    note.setWordWrap(True)
    layout.addWidget(head)
    layout.addWidget(note)
    layout.addSpacing(6)
    for w in widgets:
        layout.addWidget(w)
    layout.addStretch(1)
    return page


class LoginWizard(QWidget):
    """Страница входа в Telegram внутри главного окна."""

    finished_login = Signal()
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle("Вход в Telegram")
        self.setMinimumWidth(460)

        # --- ключи доступа: нужны до всего остального ---
        self.api_id = QLineEdit()
        self.api_id.setPlaceholderText("число с my.telegram.org")
        self.api_hash = QLineEdit()
        self.api_hash.setEchoMode(QLineEdit.Password)
        self.api_hash.setPlaceholderText("длинная строка оттуда же")
        self.show_keys = QCheckBox("Показать api_hash")
        self.show_keys.toggled.connect(
            lambda on: self.api_hash.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        # Записываем молча, как только человек ушёл из поля: отдельной кнопки
        # «Сохранить» здесь нет, и вставленный ключ не должен пропасть, если
        # человек отвлёкся и ушёл со страницы.
        for field in (self.api_id, self.api_hash):
            field.editingFinished.connect(self._save_access_quietly)

        access = QFormLayout()
        access.setHorizontalSpacing(16)
        access.addRow("api_id:", self.api_id)
        access.addRow("api_hash:", self.api_hash)
        access.addRow("", self.show_keys)
        # Кнопка вместо ссылки: раньше человек уходил на my.telegram.org и
        # оказывался там один на один с англоязычной формой, не понимая ни
        # куда жать, ни что заполнять. Сначала инструкция, ссылка — в ней.
        self.keys_help_button = QPushButton("Как получить api_id и api_hash")
        self.keys_help_button.clicked.connect(lambda: show_keys_help(self))
        access.addRow("", self.keys_help_button)
        access.addRow(ui.label(ACCESS_TEXT, tone="muted", widget=self, wrap=True))
        self.access_card = ui.card(self, "Ключи доступа", access)

        # --- страница номера ---
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+79161234567")
        self.phone_input.returnPressed.connect(self.send_phone)
        self.phone_button = QPushButton("Получить код")
        self.phone_button.clicked.connect(self.send_phone)

        # --- страница кода ---
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("12345")
        self.code_input.returnPressed.connect(self.send_code)
        self.code_button = QPushButton("Подтвердить")
        self.code_button.clicked.connect(self.send_code)
        self.restart_button = QPushButton("Ввести другой номер")
        self.restart_button.clicked.connect(lambda: self.go(PAGE_PHONE))

        # --- страница пароля ---
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self.send_password)
        self.password_button = QPushButton("Войти")
        self.password_button.clicked.connect(self.send_password)

        # --- страница «всё готово» ---
        self.who = QLabel()
        self.who.setWordWrap(True)
        self.channel_button = QPushButton("Создать канал для доставки")
        self.channel_button.setToolTip(
            "Создаст в вашем Telegram новый приватный канал и пропишет его "
            "в настройках как адрес доставки постов."
        )
        self.channel_button.clicked.connect(self.create_channel)
        self.logout_button = QPushButton("Выйти из Telegram")
        self.logout_button.clicked.connect(self.logout)

        self.pages = QStackedWidget()
        self.pages.addWidget(_page(
            "Вход в Telegram",
            "Сначала ключи доступа, потом номер телефона того аккаунта, "
            "который будет читать каналы. Telegram пришлёт код в приложение.",
            self.access_card,
            ui.label("Номер телефона", tone="muted", widget=self),
            self.phone_input, self.phone_button))
        self.pages.addWidget(_page(
            "Код подтверждения",
            "Telegram прислал код в само приложение Telegram, а не по SMS. "
            "Посмотрите там.",
            self.code_input, self.code_button, self.restart_button,
            ui.link(self, "Открыть Telegram", "https://t.me",
                    "Откроется приложение Telegram, где лежит код.")))
        self.pages.addWidget(_page(
            "Пароль двухфакторной защиты",
            "У этого аккаунта включён облачный пароль. Введите его — "
            "это не код из сообщения.",
            self.password_input, self.password_button))
        # кнопки стоят рядом и не растягиваются во всю ширину:
        # на полном экране растянутая кнопка выглядит плохо
        for button in (self.channel_button, self.logout_button):
            button.setMinimumHeight(72)
            button.setFixedWidth(260)
        done_buttons = QWidget()
        done_row = QHBoxLayout(done_buttons)
        done_row.setContentsMargins(0, 0, 0, 0)
        done_row.setSpacing(12)
        done_row.addWidget(self.channel_button)
        done_row.addWidget(self.logout_button)
        done_row.addStretch(1)

        self.pages.addWidget(_page(
            "Вход выполнен",
            "Дальше нужен канал, куда приложение будет присылать отобранные посты.\n\n"
            "Ключи доступа больше не спрашиваем — они своё дело сделали. "
            "Если когда-нибудь понадобится их поменять, они лежат в разделе "
            "«Настройки».",
            self.who, done_buttons))

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.close_button = QPushButton("Вернуться к проверке")
        self.close_button.clicked.connect(self.finished_login.emit)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)
        layout.addWidget(self.status)
        layout.addLayout(bottom)

        # закрытое окно должно исчезнуть, а не остаться слушать поток Telegram
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._links = [
            (worker.status, self.show_status),
            (worker.code_requested, self.on_code_requested),
            (worker.password_requested, self.on_password_requested),
            (worker.logged_in, self.on_logged_in),
            (worker.logged_out, self.on_logged_out),
            (worker.failed, self.on_failed),
            (worker.channel_created, self.on_channel_created),
        ]
        for signal, slot in self._links:
            signal.connect(slot)

        self.load_access()
        self.go(PAGE_PHONE)
        self.worker.check()

    def page_show(self):
        """Раздел открыли заново. Ключи могли поправить в «Настройках», а вход —
        завершиться в другом месте, поэтому перечитываем и то, и другое."""
        self.load_access()
        self.worker.check()

    def closeEvent(self, event):
        """Отписываемся явно: сигнал может прийти между закрытием и уборкой."""
        for signal, slot in self._links:
            try:
                signal.disconnect(slot)
            except Exception:
                pass          # уборка не должна мешать окну закрыться
        self._links = []
        super().closeEvent(event)

    # ---------- переключение страниц ----------

    def go(self, page):
        self.pages.setCurrentIndex(page)
        focus = {PAGE_PHONE: self.phone_input,
                 PAGE_CODE: self.code_input,
                 PAGE_PASSWORD: self.password_input}.get(page)
        if focus is not None:
            focus.setFocus()

    def _busy(self, busy):
        """Пока Telegram думает, кнопки выключены — чтобы не нажали дважды."""
        for b in (self.phone_button, self.code_button, self.password_button,
                  self.channel_button, self.logout_button):
            b.setEnabled(not busy)
        for field in (self.api_id, self.api_hash):
            field.setEnabled(not busy)

    def show_status(self, text):
        self.status.setStyleSheet("")
        self.status.setText(text)

    # ---------- ключи доступа ----------

    def load_access(self):
        """Показать в полях то, что уже сохранено. Сломанные настройки
        не должны рушить страницу: тогда поля просто останутся пустыми."""
        try:
            raw = settings.get("telegram.api_id")
            api_id = int(raw or 0)
        except (TypeError, ValueError, settings.SettingsError):
            api_id = 0
        try:
            api_hash = settings.get_secret("telegram.api_hash")
        except settings.SettingsError:
            api_hash = ""
        self.api_id.setText(str(api_id) if api_id > 0 else "")
        self.api_hash.setText(api_hash)

    def _save_access(self, complain=True):
        """Записать ключи доступа. True — можно идти дальше.

        complain=False — тихий режим: так зовётся при уходе из поля, и ругаться
        на недозаполненное там нельзя, человек ещё печатает.
        """
        api_id_text = self.api_id.text().strip()
        api_hash = self.api_hash.text().strip()

        if not api_id_text or not api_hash:
            if complain:
                self.on_failed(
                    "Заполните api_id и api_hash — без них Telegram не пустит "
                    "программу читать каналы. Где их взять, написано выше.")
            return False
        if not api_id_text.isdigit():
            if complain:
                self.on_failed("api_id — это число, букв и знаков в нём не бывает. "
                               "Длинная строка из букв и цифр — это api_hash.")
            return False

        api_id = int(api_id_text)
        try:
            was_id = int(settings.get("telegram.api_id") or 0)
            was_hash = settings.get_secret("telegram.api_hash")
        except (TypeError, ValueError, settings.SettingsError):
            was_id, was_hash = 0, ""
        if (was_id, was_hash) == (api_id, api_hash):
            return True                      # ничего не изменилось, писать нечего

        try:
            settings.save_partial(
                {"telegram": {"api_id": api_id, "api_hash": api_hash}})
        except (settings.SettingsError, OSError) as e:
            if complain:
                self.on_failed(f"Не удалось сохранить ключи доступа: {e}")
            return False

        logger.info("Ключи доступа к Telegram сохранены со страницы входа.")
        # Клиент Telethon создан на прежних ключах и про новые не знает.
        # Отпускаем сессию: следующее обращение поднимет его заново.
        self.worker.release_session()
        return True

    def _save_access_quietly(self):
        self._save_access(complain=False)

    # ---------- что делает человек ----------

    def send_phone(self):
        # ключи нужны раньше номера: без них Telegram даже не ответит
        if not self._save_access():
            return
        self._busy(True)
        self.show_status("Связываюсь с Telegram...")
        self.worker.login(self.phone_input.text())

    def send_code(self):
        self._busy(True)
        self.worker.submit_code(self.code_input.text())

    def send_password(self):
        self._busy(True)
        self.worker.submit_password(self.password_input.text())

    def logout(self):
        answer = QMessageBox.question(
            self, "Выйти из Telegram",
            "Приложение забудет вход, и в следующий раз придётся вводить номер "
            "и код заново. Выйти?")
        if answer != QMessageBox.Yes:
            return
        self._busy(True)
        self.worker.logout()

    def create_channel(self):
        answer = QMessageBox.question(
            self, "Создать канал",
            "В вашем Telegram появится новый приватный канал «Дайджест», "
            "и он будет записан в настройки как адрес доставки. Создать?")
        if answer != QMessageBox.Yes:
            return
        self._busy(True)
        self.worker.create_channel("Дайджест")

    # ---------- что отвечает Telegram ----------

    def on_code_requested(self):
        self._busy(False)
        self.code_input.clear()
        self.go(PAGE_CODE)
        self.show_status("Код отправлен.")

    def on_password_requested(self):
        self._busy(False)
        self.password_input.clear()
        self.go(PAGE_PASSWORD)
        self.show_status("Остался пароль.")

    def on_logged_in(self, name):
        self._busy(False)
        self.who.setText(f"Вы вошли как {name}.")
        self.go(PAGE_DONE)
        self.show_status("")

    def on_logged_out(self):
        self._busy(False)
        self.phone_input.clear()
        self.code_input.clear()
        self.password_input.clear()
        self.go(PAGE_PHONE)
        self.show_status("Вы вышли из Telegram.")

    def on_failed(self, text):
        self._busy(False)
        self.status.setStyleSheet(f"color: {self.error_color()};")
        self.status.setText(text)

    def on_channel_created(self, title):
        self._busy(False)
        self.show_status(f"Канал «{title}» создан и записан в настройки как адрес доставки.")

    def error_color(self):
        background = self.palette().color(self.backgroundRole())
        return "#ff8a80" if background.lightness() < 128 else "#b00020"
