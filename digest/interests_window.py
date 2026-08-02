"""Редактор интересов: текст, по которому модель решает судьбу каждого поста.

Главное здесь — не поле ввода, а проверка перед сохранением. Модель отвечает
одним словом, и код прогона ищет в ответе ровно INTERESTING или SKIP. Если из
текста пропадёт требование отвечать этими словами, фильтр не сломается заметно:
он начнёт молча пропускать всё подряд. Поэтому сохранить текст без них нельзя.
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

import ui
from core import paths, settings
from core.logs import logger

HEAD_TEXT = 'Здесь вы объясняете модели, какие посты вам нужны. Этот текст уходит ей вместе с каждым постом, и по нему принимается решение — переслать пост или пропустить.\n\nПишите обычными словами: перечислите темы, которые вам интересны, и то, что нужно отсеивать. Чем понятнее сформулировано, тем точнее отбор.\n\nСлова INTERESTING и SKIP обязательны и удалять их нельзя. Модель отвечает одним словом, а программа ищет в ответе ровно эти два. Без них фильтр не сломается заметно — он начнёт молча пропускать всё подряд, и в канал польётся поток.'

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

        head = ui.label(HEAD_TEXT, wrap=True)

        self.editor = QPlainTextEdit()
        # моноширинный и того же размера, что журнал: длинный текст фильтра
        # обычным шрифтом читать тяжело
        self.editor.setFont(ui.mono_font())
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.textChanged.connect(self.update_counter)

        self.counter = QLabel()
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.restore_button = QPushButton("Вернуть шаблон по умолчанию")
        self.restore_button.setToolTip(
            "Заменит текст на короткую заготовку, которая пришла вместе "
            "с программой. Ваши правки в окне пропадут.")
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
        """Кнопка живёт, только если шаблон вообще есть рядом с программой."""
        exists = os.path.exists(paths.interests_template())
        self.restore_button.setEnabled(exists)
        if not exists:
            self.restore_button.setToolTip(
                "Файл шаблона не найден рядом с программой — возвращать нечего.")

    def restore_template(self):
        answer = QMessageBox.warning(
            self, "Вы уверены?",
            "Текст фильтра будет заменён на короткий шаблон по умолчанию.\n"
            "Всё, что вы написали, пропадёт.\n\n"
            "Если текст уже сохранён, он всё равно останется в файле, пока "
            "вы не нажмёте «Сохранить».",
            QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Ok:
            return
        try:
            with open(paths.interests_template(), "r", encoding="utf-8-sig") as f:
                self.editor.setPlainText(f.read())
        except OSError as e:
            self.show_message(f"Не удалось прочитать заготовку: {e}", error=True)
            return
        self.show_message("Шаблон подставлен. Нажмите «Сохранить», чтобы записать.")

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
