"""Редактор интересов: текст, по которому модель решает судьбу каждого поста.

Главное здесь — не поле ввода, а проверка перед сохранением. Модель отвечает
одним словом, и код прогона ищет в ответе ровно INTERESTING или SKIP. Если из
текста пропадёт требование отвечать этими словами, фильтр не сломается заметно:
он начнёт молча пропускать всё подряд. Поэтому сохранить текст без них нельзя.
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from core import paths, settings
from core.logs import logger

VERDICTS = ("INTERESTING", "SKIP")
# ориентир по длине: промпт плюс сам пост должны помещаться в окно модели
LONG_TEXT = 20000


def text_problems(text):
    """Претензии к тексту интересов. Пустой список — можно сохранять."""
    out = []
    if not text.strip():
        out.append("Текст пуст. Без него модель не поймёт, что вам нужно.")
        return out
    missing = [word for word in VERDICTS if word not in text]
    if missing:
        out.append(
            "В тексте не осталось слов " + " и ".join(missing) +
            ". Программа ждёт от модели ответ ровно этими словами: без них "
            "фильтр перестанет отличать нужное от ненужного и пропустит всё подряд."
        )
    if len(text) > LONG_TEXT:
        out.append(
            f"Текст очень длинный ({len(text)} знаков). Он уходит модели с каждым "
            "постом: чем длиннее, тем медленнее прогон."
        )
    return out


class InterestsWindow(QWidget):
    """Страница интересов внутри главного окна."""

    saved = Signal()
    cancelled = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Интересы")
        self.resize(820, 640)

        head = QLabel(
            "По этому тексту модель решает, интересен ли пост. Правьте осторожно: "
            "текст выверен прогонами, и каждая переформулировка меняет отбор."
        )
        head.setWordWrap(True)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.textChanged.connect(self.update_counter)

        self.counter = QLabel()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.restore_button = QPushButton("Вернуть заготовку")
        self.restore_button.setToolTip(
            "Заменит текст на тот, что пришёл вместе с программой.")
        self.restore_button.clicked.connect(self.restore_template)

        save_button = QPushButton("Сохранить")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.cancel)

        bottom = QHBoxLayout()
        bottom.addWidget(self.restore_button)
        bottom.addStretch(1)
        bottom.addWidget(cancel_button)
        bottom.addWidget(save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addWidget(self.editor)
        layout.addWidget(self.counter)
        layout.addWidget(self.message)
        layout.addLayout(bottom)

        # закрытое окно не должно оставаться жить у родителя
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.load_text()

    # ---------- чтение и запись ----------

    def load_text(self):
        try:
            self.editor.setPlainText(settings.interests())
            self.show_message("")
        except settings.SettingsError as e:
            self.editor.setPlainText("")
            self.show_message(str(e), error=True)
        self._saved_text = self.editor.toPlainText()
        self.update_counter()
        self._sync_restore_button()

    def _sync_restore_button(self):
        """В портативном режиме заготовка и рабочий файл — это один и тот же
        файл. Кнопка «вернуть заготовку» тогда не значит ничего и только
        сбивает с толку."""
        template = paths.interests_template()
        same_file = os.path.abspath(template) == os.path.abspath(paths.interests_file())
        self.restore_button.setEnabled(os.path.exists(template) and not same_file)
        if same_file:
            self.restore_button.setToolTip(
                "Здесь программа работает из своей папки, и заготовка — это тот же "
                "самый файл. Возвращать нечего.")

    def restore_template(self):
        answer = QMessageBox.question(
            self, "Вернуть заготовку",
            "Заменить текст на тот, что пришёл вместе с программой? "
            "Ваши правки в окне пропадут.")
        if answer != QMessageBox.Yes:
            return
        try:
            with open(paths.interests_template(), "r", encoding="utf-8-sig") as f:
                self.editor.setPlainText(f.read())
        except OSError as e:
            self.show_message(f"Не удалось прочитать заготовку: {e}", error=True)
            return
        self.show_message("Заготовка подставлена. Нажмите «Сохранить», чтобы записать.")

    def save(self):
        text = self.editor.toPlainText()
        troubles = text_problems(text)
        blocking = [t for t in troubles if "очень длинный" not in t]
        if blocking:
            self.show_message(" ".join(blocking), error=True)
            return
        if troubles:
            answer = QMessageBox.question(self, "Длинный текст",
                                          troubles[0] + "\n\nВсё равно сохранить?")
            if answer != QMessageBox.Yes:
                return
        try:
            path = settings.save_interests(text)
        except OSError as e:
            self.show_message(f"Не удалось записать файл: {e}", error=True)
            return
        logger.info(f"Текст интересов сохранён: {path} ({len(text)} знаков)")
        self._saved_text = text
        self.saved.emit()

    # ---------- страница ----------

    def has_changes(self):
        return self.editor.toPlainText() != self._saved_text

    def page_show(self):
        self.load_text()

    def cancel(self):
        self.load_text()
        self.cancelled.emit()

    # ---------- мелочи ----------

    def update_counter(self):
        text = self.editor.toPlainText()
        found = [word for word in VERDICTS if word in text]
        verdicts = ", ".join(found) if found else "НЕ НАЙДЕНЫ"
        self.counter.setText(f"Знаков: {len(text)}    Слова-вердикты: {verdicts}")
        self.counter.setStyleSheet(
            "" if len(found) == len(VERDICTS) else f"color: {self.error_color()};")

    def show_message(self, text, error=False):
        self.message.setStyleSheet(f"color: {self.error_color()};" if error else "")
        self.message.setText(text)

    def error_color(self):
        background = self.palette().color(self.backgroundRole())
        return "#ff8a80" if background.lightness() < 128 else "#b00020"
