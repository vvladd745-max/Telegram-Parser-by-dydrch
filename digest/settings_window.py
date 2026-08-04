"""Экран настроек: то, что человек вводит руками.

Каналы и текст интересов сюда НЕ входят — им нужны свои экраны, они будут
отдельно. Здесь только поля: доступ к Telegram, глубина просмотра, модель и
отчёты боту.

Всё, что вводится, сохраняется по нажатию «Сохранить» и только теми ключами,
которые есть на экране: список каналов и прочее остаётся нетронутым.

Секреты — api_hash, токен бота, ключ модели — уходят не в файл, а в Диспетчер
учётных данных Windows; в settings.json на их месте остаётся пусто. Если
хранилище недоступно, значение остаётся в файле: потерять введённый пароль
хуже, чем сохранить его открытым текстом.
"""
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

import ui
from core import llm, settings
from core.logs import logger
from runner import topics_available


TIP_API = 'Ключи вашего личного приложения Telegram — программа читает каналы от вашего имени.\n\nГде взять: my.telegram.org → войдите по номеру телефона → API development tools →\nзаполните простую форму (название любое). Telegram выдаст api_id (число)\nи api_hash (длинная строка из букв и цифр).\n\nВыдаются бесплатно и один раз, никому их не показывайте.'

TIP_BOT = 'Бот присылает в Telegram короткий итог: сколько постов проверено и сколько отобрано.\n\nБез бота уведомлений не будет — придётся самому открывать окно программы\nи смотреть, закончилась проверка или ещё идёт.\n\nГде взять: напишите @BotFather команду /newbot — он выдаст токен.\nСвой chat_id узнаете у @userinfobot.'

TIP_MODEL = 'Программа проверена только на Qwen3-8B-128K в LM Studio: с ней отбор постов\nработает так, как задумано.\n\nСюда можно вписать любую другую модель — и локальную поменьше, и облачную\nпо адресу с ключом. Технически это работает, но как чужая модель справится\nс отбором постов, мы не проверяли и обещать ничего не можем.\n\nЕсли поменяли — нажмите «Проверить модель», а потом прогоните тестовую\nпроверку: на ней видно, разумно ли модель отбирает.'


TIP_TOPICS = 'Сразу после проверки постов программа соберёт темы для будущих статей:\nпосмотрит, что люди ищут в поисковиках по вашим направлениям, и пришлёт\nсписок в Telegram вместе с полной выгрузкой в файле.\n\nЭто прибавляет к проверке заметное время — темы собираются по многим\nзапросам подряд. Кнопка «Остановить» прерывает проверку постов, но не сбор тем:\nначатый сбор доходит до конца.\n\nЧто искать — задаётся списком направлений, он живёт отдельно от каналов.'


class ModelCheck(QThread):
    """Проверка модели в отдельном потоке: сеть не должна морозить окно."""

    done = Signal(bool, str)

    def __init__(self, url, name, key, parent=None):
        super().__init__(parent)
        self._args = (url, name, key)

    def run(self):
        url, name, key = self._args
        ok, text = llm.probe(url=url, name=name, key=key)
        logger.info(f"Проверка модели: {'успех' if ok else 'неудача'} — {text}")
        self.done.emit(ok, text)


def _secret_field():
    field = QLineEdit()
    field.setEchoMode(QLineEdit.Password)
    return field


def _hours_field(low, high, suffix=" ч"):
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    return box


class SettingsWindow(QWidget):
    """Страница настроек внутри главного окна."""

    saved = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(560)
        self._check = None

        # --- доступ к Telegram ---
        self.api_id = QLineEdit()
        self.api_id.setPlaceholderText("число с my.telegram.org")
        self.api_hash = _secret_field()
        self.target = QLineEdit()
        self.target.setPlaceholderText("@канал или числовой адрес приватного канала")

        tg = QFormLayout()
        tg.addRow(ui.labeled(self, "api_id:", TIP_API), self.api_id)
        tg.addRow(ui.labeled(self, "api_hash:", TIP_API), self.api_hash)
        tg.addRow("Куда слать посты:", self.target)
        tg.addRow("", ui.link(self, "Получить api_id и api_hash на my.telegram.org",
                              "https://my.telegram.org/apps",
                              "Откроется в браузере. Войдите по номеру телефона, "
                              "раздел API development tools."))
        tg_box = QGroupBox("Доступ к Telegram")
        tg_box.setLayout(tg)

        # --- глубина просмотра ---
        self.lookback = _hours_field(1, 240)
        self.dry_run = _hours_field(1, 240)
        depth = QFormLayout()
        depth.addRow("Первая проверка канала:", self.lookback)
        depth.addRow("Тестовая проверка:", self.dry_run)
        depth_box = QGroupBox("Длительность проверки")
        depth_box.setLayout(depth)
        self.lookback.setToolTip(
            "За сколько часов брать посты, когда канал читается впервые. "
            "Дальше программа помнит, где остановилась, и берёт только новое."
        )
        self.dry_run.setToolTip(
            "За сколько часов брать посты в тестовой проверке. Она ничего\n"
            "не пересылает и не двигает закладки — только показывает результат.")

        # --- модель ---
        self.model_url = QLineEdit()
        self.model_name = QLineEdit()
        self.model_key = _secret_field()
        self.model_key.setPlaceholderText("для LM Studio не нужен")
        self.check_button = QPushButton("Проверить модель")
        self.check_button.clicked.connect(self.run_check)
        self.check_result = QLabel()
        self.check_result.setWordWrap(True)
        self.check_result.setTextInteractionFlags(Qt.TextSelectableByMouse)

        model = QFormLayout()
        # Кругляшок стоит на обеих строках, как у api_id и api_hash: модель
        # меняют то адресом (облачная), то именем (другая локальная), и человек
        # смотрит на то поле, которое правит.
        model.addRow(ui.labeled(self, "Адрес:", TIP_MODEL), self.model_url)
        model.addRow(ui.labeled(self, "Имя модели:", TIP_MODEL), self.model_name)
        model.addRow("Ключ:", self.model_key)
        model.addRow("", self.check_button)
        model.addRow("", self.check_result)
        model.addRow("", ui.link(self, "Скачать LM Studio", "https://lmstudio.ai",
                                 "Программа, которая запускает ИИ-модель "
                                 "на вашем компьютере."))
        model_box = QGroupBox("ИИ-модель для анализа постов")
        model_box.setLayout(model)

        # --- отчёты боту ---
        self.bot_enabled = QCheckBox("Присылать отчёт о проверке ботом")
        self.bot_enabled.toggled.connect(self._sync_bot_fields)
        self.bot_token = _secret_field()
        self.bot_chat = QLineEdit()
        self.bot_chat.setPlaceholderText("числовой id получателя")
        # кругляшок ставим рядом с самой галочкой: отдельной подписью
        # получалась вторая строка про то же самое
        bot_head = QWidget()
        bot_row = QHBoxLayout(bot_head)
        bot_row.setContentsMargins(0, 0, 0, 0)
        bot_row.setSpacing(6)
        bot_row.addWidget(self.bot_enabled)
        bot_row.addWidget(ui.hint(self, TIP_BOT))
        bot_row.addStretch(1)

        bot_links = QWidget()
        bot_links_row = QHBoxLayout(bot_links)
        bot_links_row.setContentsMargins(0, 0, 0, 0)
        bot_links_row.setSpacing(16)
        bot_links_row.addWidget(ui.link(self, "Создать бота — @BotFather",
                                        "https://t.me/BotFather",
                                        "Откроется в Telegram. Команда /newbot — "
                                        "и он выдаст токен."))
        bot_links_row.addWidget(ui.link(self, "Узнать свой chat_id — @userinfobot",
                                        "https://t.me/userinfobot",
                                        "Откроется в Telegram. Напишите ему что угодно, "
                                        "он ответит вашим номером."))
        bot_links_row.addStretch(1)

        bot = QFormLayout()
        bot.addRow(bot_head)
        bot.addRow("Токен бота:", self.bot_token)
        bot.addRow("chat_id:", self.bot_chat)
        bot.addRow("", bot_links)
        bot_box = QGroupBox("Отчёты")
        bot_box.setLayout(bot)

        # --- темы для статей ---
        # Раздела может не быть вовсе: у коллег личного инструмента нет, и
        # показывать им галочку значило бы предлагать включить пустое место.
        self.find_topics = None
        topics_box = None
        if topics_available():
            self.find_topics = QCheckBox("Искать темы для статей после проверки")
            # кругляшок рядом с галочкой, как у отчётов боту
            topics_head = QWidget()
            topics_row = QHBoxLayout(topics_head)
            topics_row.setContentsMargins(0, 0, 0, 0)
            topics_row.setSpacing(6)
            topics_row.addWidget(self.find_topics)
            topics_row.addWidget(ui.hint(self, TIP_TOPICS))
            topics_row.addStretch(1)

            topics = QFormLayout()
            topics.addRow(topics_head)
            topics_box = QGroupBox("Темы для статей")
            topics_box.setLayout(topics)

        # --- вид ---
        self.matrix_box = QCheckBox("Печатать журнал проверки как в «Матрице»")
        self.matrix_box.setToolTip(
            "Посимвольная печать зелёным. Снимите галочку — включится обычный "
            "информативный вывод: строки появляются целиком и сразу.")
        self.theme_box = QComboBox()
        for key, name in ui.THEMES.items():
            self.theme_box.addItem(name, key)
        self.theme_box.setToolTip(
            "«Как в системе» — окно подстраивается под настройку Windows.\n"
            "Светлую или тёмную можно выбрать вручную, если системная не нравится.")

        self.font_box = QSpinBox()
        self.font_box.setRange(0, 20)
        self.font_box.setSpecialValueText("как в системе")
        self.font_box.setSuffix(" пт")
        self.font_box.setToolTip(
            "Размер букв во всём приложении. Ноль — взять из настроек Windows.\n"
            "Обычные значения: 9 мелко, 11 средне, 14 крупно.")

        view = QFormLayout()
        view.addRow(self.matrix_box)
        view.addRow("Тема:", self.theme_box)
        view.addRow("Размер букв:", self.font_box)
        view_box = QGroupBox("Внешний вид")
        view_box.setLayout(view)

        # --- низ окна ---
        self.show_secrets = QCheckBox("Показать секреты")
        self.show_secrets.toggled.connect(self._sync_secret_echo)

        self.message = QLabel()
        self.message.setWordWrap(True)

        save_button = QPushButton("Сохранить")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.cancel)

        bottom = QHBoxLayout()
        bottom.addWidget(self.show_secrets)
        bottom.addStretch(1)
        bottom.addWidget(cancel_button)
        bottom.addWidget(save_button)

        layout = QVBoxLayout(self)
        for box in (tg_box, depth_box, model_box, bot_box, topics_box, view_box):
            if box is not None:      # раздела тем может не быть
                layout.addWidget(box)
        layout.addWidget(self.message)
        layout.addLayout(bottom)

        # закрытое окно не должно оставаться жить у родителя
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.load_values()

    # ---------- чтение и запись ----------

    def load_values(self):
        """Заполняет поля тем, что сейчас в settings.json."""
        try:
            settings.load(force=True)
        except settings.SettingsError as e:
            self.show_message(str(e), error=True)
            return
        self.api_id.setText(str(settings.get("telegram.api_id") or ""))
        self.api_hash.setText(settings.get_secret("telegram.api_hash"))
        self.target.setText(str(settings.get("telegram.target") or ""))
        self.lookback.setValue(int(settings.get("digest.lookback_hours") or 28))
        self.dry_run.setValue(int(settings.get("digest.dry_run_hours") or 2))
        self.model_url.setText(str(settings.get("model.url") or ""))
        self.model_name.setText(str(settings.get("model.name") or ""))
        self.model_key.setText(settings.get_secret("model.api_key"))
        self.bot_enabled.setChecked(bool(settings.get("bot.enabled")))
        self.bot_token.setText(settings.get_secret("bot.token"))
        self.bot_chat.setText(str(settings.get("bot.chat_id") or ""))
        if self.find_topics is not None:
            self.find_topics.setChecked(bool(settings.get("digest.find_topics", False)))
        self.matrix_box.setChecked(bool(settings.get("ui.matrix", True)))
        theme = str(settings.get("ui.theme", "system"))
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(theme)))
        self.font_box.setValue(int(settings.get("ui.font_size", 0) or 0))
        self._sync_bot_fields()
        self._sync_secret_echo()
        self._saved_snapshot = self.snapshot()

    def collect(self):
        """Проверяет введённое. Возвращает (значения, список претензий)."""
        troubles = []

        api_id_text = self.api_id.text().strip()
        api_id = 0
        if api_id_text:
            if api_id_text.isdigit():
                api_id = int(api_id_text)
            else:
                troubles.append("api_id — это число, буквы и знаки в нём не бывают.")

        chat_text = self.bot_chat.text().strip()
        chat_id = 0
        if chat_text:
            if chat_text.lstrip("-").isdigit():
                chat_id = int(chat_text)
            else:
                troubles.append("chat_id — это число, его выдаёт @userinfobot.")

        target = self.target.text().strip()
        if self.bot_enabled.isChecked() and not self.bot_token.text().strip():
            troubles.append("Отчёты боту включены, но токен бота пуст.")

        digest_values = {"lookback_hours": self.lookback.value(),
                         "dry_run_hours": self.dry_run.value()}
        # Галочки может не быть вовсе. Тогда ключ в файле не трогаем: иначе
        # окно затирало бы настройку, которой у него нет и не должно быть.
        if self.find_topics is not None:
            digest_values["find_topics"] = self.find_topics.isChecked()

        values = {
            "telegram": {"api_id": api_id,
                         "api_hash": self.api_hash.text().strip(),
                         "target": target},
            "digest": digest_values,
            "model": {"url": self.model_url.text().strip(),
                      "name": self.model_name.text().strip(),
                      "api_key": self.model_key.text().strip()},
            "bot": {"enabled": self.bot_enabled.isChecked(),
                    "token": self.bot_token.text().strip(),
                    "chat_id": chat_id},
            "ui": {"matrix": self.matrix_box.isChecked(),
                   "theme": self.theme_box.currentData(),
                   "font_size": self.font_box.value()},
        }
        return values, troubles

    def save(self):
        values, troubles = self.collect()
        if troubles:
            self.show_message(" ".join(troubles), error=True)
            return
        try:
            data = settings.load(force=True)
            for section, fields in values.items():
                data.setdefault(section, {}).update(fields)
            # секреты уводим в Диспетчер учётных данных, а в файле оставляем пусто.
            # Если хранилище недоступно, значение остаётся в файле — иначе
            # человек ввёл бы пароль, а он бы просто пропал.
            for path in settings.SECRET_PATHS:
                section, key = path.split(".", 1)
                secret = data.get(section, {}).get(key, "")
                if secret and settings.set_secret(path, secret):
                    data[section][key] = ""
            settings.save(data)
        except settings.SettingsError as e:
            self.show_message(str(e), error=True)
            return
        except OSError as e:
            self.show_message(f"Не удалось записать настройки: {e}", error=True)
            return
        logger.info("Настройки сохранены из окна.")
        self._saved_snapshot = self.snapshot()
        self.saved.emit()

    # ---------- страница ----------

    def snapshot(self):
        """Слепок полей — чтобы понять, есть ли несохранённые правки."""
        return (self.api_id.text(), self.api_hash.text(), self.target.text(),
                self.lookback.value(), self.dry_run.value(),
                self.model_url.text(), self.model_name.text(), self.model_key.text(),
                self.bot_enabled.isChecked(), self.bot_token.text(), self.bot_chat.text(),
                self.find_topics.isChecked() if self.find_topics is not None else None,
                self.matrix_box.isChecked(), self.theme_box.currentData(),
                self.font_box.value())

    def has_changes(self):
        return self.snapshot() != self._saved_snapshot

    def page_show(self):
        """Вход на страницу: перечитываем настройки с диска."""
        self.load_values()

    def cancel(self):
        self.load_values()
        self.cancelled.emit()

    # ---------- проверка модели ----------

    def run_check(self):
        if self._check is not None and self._check.isRunning():
            return
        self.check_button.setEnabled(False)
        self.check_result.setStyleSheet("")
        self.check_result.setText("Спрашиваю модель...")
        self._check = ModelCheck(self.model_url.text().strip(),
                                 self.model_name.text().strip(),
                                 self.model_key.text().strip(), self)
        self._check.done.connect(self.on_check_done)
        self._check.start()

    def on_check_done(self, ok, text):
        self.check_button.setEnabled(True)
        self.check_result.setStyleSheet("" if ok else f"color: {self.error_color()};")
        self.check_result.setText(text)

    # ---------- мелочи оформления ----------

    def _sync_secret_echo(self):
        mode = QLineEdit.Normal if self.show_secrets.isChecked() else QLineEdit.Password
        for field in (self.api_hash, self.model_key, self.bot_token):
            field.setEchoMode(mode)

    def _sync_bot_fields(self):
        on = self.bot_enabled.isChecked()
        self.bot_token.setEnabled(on)
        self.bot_chat.setEnabled(on)

    def show_message(self, text, error=False):
        self.message.setStyleSheet(f"color: {self.error_color()};" if error else "")
        self.message.setText(text)

    def error_color(self):
        background = self.palette().color(self.backgroundRole())
        return "#ff8a80" if background.lightness() < 128 else "#b00020"

    def closeEvent(self, event):
        if self._check is not None and self._check.isRunning():
            self._check.wait(3000)
        super().closeEvent(event)
