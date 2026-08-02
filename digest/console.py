"""Окно журнала проверки с посимвольной печатью — «как в Матрице».

Зачем отдельный класс. Строки прогона приходят рывками: канал молчит,
потом сразу пять постов. Если печатать их посимвольно с постоянной
скоростью, журнал начнёт отставать от происходящего, и к концу прогона
человек будет смотреть кино про то, что случилось пять минут назад.

Поэтому скорость печати зависит от длины очереди: чем больше накопилось,
тем крупнее куски. Когда очередь совсем большая — вываливаем строки целиком.
Красота важна, но правда о происходящем важнее.
"""
from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

import ui

# Зелёный для тёмной темы. На светлой зелёный по белому не читается,
# поэтому там обычный чёрный текст — печать остаётся, кислота уходит.
MATRIX_GREEN = "#3ddc84"

TICK_MS = 12          # как часто дописываем
BASE_CHARS = 2        # символов за тик, когда всё спокойно
RUSH_QUEUE = 8        # с этой длины очереди начинаем ускоряться
DUMP_QUEUE = 60       # а с этой печатать посимвольно уже нечестно


class RunConsole(QPlainTextEdit):
    """Журнал проверки. append_line() — единственный способ добавить строку."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setFont(ui.mono_font())

        self._queue = deque()
        self._line = ""          # строка, которую печатаем прямо сейчас
        self._at = 0             # сколько символов из неё уже напечатано
        self._matrix = True

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.set_matrix(True)

    # ---------- настройка ----------

    def set_matrix(self, on):
        """Матричная печать или обычный вывод целыми строками."""
        self._matrix = bool(on)
        if not self._matrix:
            self._flush_all()
        self._apply_style()

    def _apply_style(self):
        dark = ui.is_dark(self._owner)
        text_color = MATRIX_GREEN if (self._matrix and dark) else ui.color(self._owner, "text")
        self.setObjectName("console")
        self.setStyleSheet(
            f"#console {{ background: {ui.color(self._owner, 'panel')};"
            f" border: 1px solid {ui.color(self._owner, 'line')}; border-radius: 6px;"
            f" padding: 6px; color: {text_color}; }}")

    # ---------- добавление строк ----------

    def append_line(self, text):
        for piece in str(text).split("\n"):
            self._queue.append(piece)
        if self._matrix:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._flush_all()

    def set_hint(self, text):
        """Подсказка до первой проверки. Печатается сразу, без анимации."""
        self.stop()
        self.setPlainText(text)

    def clear(self):
        self.stop()
        super().clear()

    def stop(self):
        self._timer.stop()
        self._queue.clear()
        self._line = ""
        self._at = 0

    # ---------- сама печать ----------

    def _tick(self):
        if self._at >= len(self._line):
            if not self._queue:
                self._timer.stop()
                return
            if self._line:
                self._write("\n")
            self._line = self._queue.popleft()
            self._at = 0
            if len(self._queue) > DUMP_QUEUE:
                # накопилось столько, что посимвольная печать врала бы
                # о происходящем — досыпаем разом
                self._write(self._line)
                self._at = len(self._line)
                self._flush_all(keep_timer=True)
                return

        chunk = BASE_CHARS
        if len(self._queue) > RUSH_QUEUE:
            chunk += len(self._queue)          # догоняем: чем больше ждёт, тем быстрее
        piece = self._line[self._at:self._at + chunk]
        self._at += len(piece)
        self._write(piece)

    def _flush_all(self, keep_timer=False):
        """Дописать всё, что ждёт, разом."""
        rest = self._line[self._at:]
        if rest:
            self._write(rest)
        self._line = ""
        self._at = 0
        while self._queue:
            self._write("\n" + self._queue.popleft())
        if not keep_timer:
            self._timer.stop()

    def _write(self, text):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
