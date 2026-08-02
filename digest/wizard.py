"""Окно входа в Telegram: номер, код, пароль двухфакторной защиты.

Окно ничего не делает само — оно только показывает страницы и передаёт
введённое в рабочий поток (digest/tgclient.py), а обратно получает сигналы.
Поэтому оно не замирает, пока Telegram думает.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QMessageBox,
)

PAGE_PHONE, PAGE_CODE, PAGE_PASSWORD, PAGE_DONE = range(4)


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
            "Введите номер телефона того аккаунта, который читает каналы. "
            "Telegram пришлёт код в приложение.",
            self.phone_input, self.phone_button))
        self.pages.addWidget(_page(
            "Код подтверждения",
            "Telegram прислал код в само приложение Telegram, а не по SMS. "
            "Посмотрите там.",
            self.code_input, self.code_button, self.restart_button))
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
            "Дальше нужен канал, куда приложение будет присылать отобранные посты.",
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

        self.go(PAGE_PHONE)
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

    def show_status(self, text):
        self.status.setStyleSheet("")
        self.status.setText(text)

    # ---------- что делает человек ----------

    def send_phone(self):
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
