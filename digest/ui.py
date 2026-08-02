"""Язык оформления окон: цвета, кнопки, карточки.

Одно место на всё приложение — чтобы экраны выглядели одинаково и чтобы
менять вид можно было здесь, а не в пяти файлах сразу.

Главное правило: цвета берутся из системной палитры и подбираются под
светлую или тёмную тему Windows. Прибитый гвоздями цвет однажды уже сделал
список ошибок нечитаемым на тёмном фоне — повторять не будем.
"""
from PySide6.QtCore import Qt
import os

from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QPalette

from core import paths

# Роли цветов. Слева — тёмная тема, справа — светлая.
_PALETTE = {
    "muted":  ("#9aa0a6", "#6b7075"),   # подписи, второстепенное
    "accent": ("#5aa9ff", "#0b63ce"),   # главное действие
    "ok":     ("#7bd88f", "#1a7f37"),   # всё хорошо
    "bad":    ("#ff8a80", "#b00020"),   # ошибка, требует внимания
    "line":   ("#3a3d41", "#d8dade"),   # рамки и разделители
    "panel":  ("#242629", "#f6f7f9"),   # фон карточек и боковой панели
}


def is_dark(widget):
    return widget.palette().color(QPalette.Window).lightness() < 128


def color(widget, role):
    """Цвет роли под текущую тему. role="text" — обычный текст из палитры."""
    if role == "text":
        return widget.palette().color(QPalette.WindowText).name()
    dark, light = _PALETTE[role]
    return dark if is_dark(widget) else light


def label(text="", size=None, bold=False, tone=None, widget=None, wrap=False,
          selectable=False):
    """Подпись. tone — роль цвета из палитры выше (нужен widget)."""
    lab = QLabel(text)
    font = lab.font()
    if size:
        font.setPointSize(size)
    font.setBold(bold)
    lab.setFont(font)
    if tone and widget is not None:
        lab.setStyleSheet(f"color: {color(widget, tone)};")
    lab.setWordWrap(wrap)
    if selectable:
        # пути длинные, их хочется выделить и скопировать
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def card(widget, caption, inner):
    """Карточка с мелким заголовком и содержимым.

    Стиль задаётся по имени объекта, а НЕ по типу QFrame: QLabel в Qt
    унаследован от QFrame, и правило "QFrame {...}" разрисовало бы рамками
    все подписи внутри.
    """
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(
        f"#card {{ background: {color(widget, 'panel')};"
        f" border: 1px solid {color(widget, 'line')}; border-radius: 8px; }}")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(8)
    if caption:
        cap = label(caption.upper(), size=8, bold=True, tone="muted", widget=widget)
        layout.addWidget(cap)
    layout.addLayout(inner)
    return frame


def primary_button(widget, text):
    """Главное действие на экране. Такая кнопка должна быть одна."""
    button = QPushButton(text)
    accent = color(widget, "accent")
    button.setMinimumHeight(32)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton {{ background: {accent}; color: white; border: none;"
        f" border-radius: 6px; padding: 6px 18px; font-weight: bold; }}"
        f"QPushButton:hover {{ background: {QColor(accent).lighter(115).name()}; }}"
        f"QPushButton:disabled {{ background: {color(widget, 'line')};"
        f" color: {color(widget, 'muted')}; }}")
    return button


def flat_button(widget, text):
    """Обычное действие: рамка без заливки."""
    button = QPushButton(text)
    button.setMinimumHeight(30)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {color(widget, 'text')};"
        f" border: 1px solid {color(widget, 'line')}; border-radius: 6px;"
        f" padding: 5px 14px; }}"
        f"QPushButton:hover {{ background: {color(widget, 'panel')}; }}"
        f"QPushButton:disabled {{ color: {color(widget, 'muted')};"
        f" border-color: {color(widget, 'panel')}; }}")
    return button


def nav_button(widget, text, active=False):
    """Пункт боковой панели. Активный залит акцентом."""
    button = QPushButton("   " + text)
    button.setMinimumHeight(32)
    button.setCursor(Qt.PointingHandCursor)
    if active:
        button.setStyleSheet(
            f"QPushButton {{ background: {color(widget, 'accent')}; color: white;"
            f" border: none; border-radius: 6px; padding: 6px 12px;"
            f" text-align: left; font-weight: bold; }}")
    else:
        button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {color(widget, 'text')};"
            f" border: none; border-radius: 6px; padding: 6px 12px; text-align: left; }}"
            f"QPushButton:hover {{ background: {color(widget, 'line')}; }}"
            f"QPushButton:disabled {{ color: {color(widget, 'muted')}; }}")
    return button


def hint(widget, text):
    """Кругляшок «?» с пояснением при наведении.

    Пояснение пишем для человека, который впервые открыл программу:
    что это, зачем нужно и где взять.
    """
    badge = QLabel("?")
    badge.setAlignment(Qt.AlignCenter)
    badge.setFixedSize(18, 18)
    badge.setToolTip(text)
    badge.setCursor(Qt.WhatsThisCursor)
    badge.setObjectName("hint")
    badge.setStyleSheet(
        f"#hint {{ color: {color(widget, 'muted')};"
        f" border: 1px solid {color(widget, 'line')}; border-radius: 9px;"
        f" font-weight: bold; }}")
    return badge


def labeled(widget, text, tip):
    """Подпись поля с кругляшком-подсказкой рядом."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(QLabel(text))
    row.addWidget(hint(widget, tip))
    row.addStretch(1)
    return holder


# Тема и размер букв применяются ко всему приложению разом. Родные настройки
# запоминаем при первом вызове, чтобы можно было вернуться к системным.
_BASE_STYLE = None
_BASE_PALETTE = None
_BASE_FONT_SIZE = None

THEMES = {"system": "Как в системе", "light": "Светлая", "dark": "Тёмная"}


def _dark_palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#1e1f22"))
    p.setColor(QPalette.WindowText, QColor("#e6e6e6"))
    p.setColor(QPalette.Base, QColor("#17181a"))
    p.setColor(QPalette.AlternateBase, QColor("#242629"))
    p.setColor(QPalette.Text, QColor("#e6e6e6"))
    p.setColor(QPalette.Button, QColor("#2a2c30"))
    p.setColor(QPalette.ButtonText, QColor("#e6e6e6"))
    p.setColor(QPalette.ToolTipBase, QColor("#2a2c30"))
    p.setColor(QPalette.ToolTipText, QColor("#e6e6e6"))
    p.setColor(QPalette.Highlight, QColor("#5aa9ff"))
    p.setColor(QPalette.HighlightedText, QColor("#101114"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#8a8f95"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8a8f95"))
    return p


def _light_palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#f2f3f5"))
    p.setColor(QPalette.WindowText, QColor("#1b1c1e"))
    p.setColor(QPalette.Base, QColor("#ffffff"))
    p.setColor(QPalette.AlternateBase, QColor("#eceef1"))
    p.setColor(QPalette.Text, QColor("#1b1c1e"))
    p.setColor(QPalette.Button, QColor("#f2f3f5"))
    p.setColor(QPalette.ButtonText, QColor("#1b1c1e"))
    p.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    p.setColor(QPalette.ToolTipText, QColor("#1b1c1e"))
    p.setColor(QPalette.Highlight, QColor("#0b63ce"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#8a8f95"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8a8f95"))
    return p


def apply_theme(app, mode="system"):
    """Тема окна: как в системе, светлая или тёмная.

    Своя тема ставится вместе со стилем Fusion: родной стиль Windows часть
    цветов рисует сам и палитру игнорирует — получилось бы наполовину светлое
    окно на тёмной теме.
    """
    global _BASE_STYLE, _BASE_PALETTE
    if _BASE_STYLE is None:
        _BASE_STYLE = app.style().objectName()
        _BASE_PALETTE = QPalette(app.palette())
    if mode == "dark":
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
    elif mode == "light":
        app.setStyle("Fusion")
        app.setPalette(_light_palette())
    else:
        app.setStyle(_BASE_STYLE)
        app.setPalette(_BASE_PALETTE)


def apply_base_font(app, size=0, delta=1):
    """Размер букв во всём приложении. size=0 — системный плюс delta:
    системный на большом экране мелковат."""
    global _BASE_FONT_SIZE
    font = app.font()
    if _BASE_FONT_SIZE is None:
        _BASE_FONT_SIZE = font.pointSize()
    font.setPointSize(int(size) if size else max(8, _BASE_FONT_SIZE + delta))
    app.setFont(font)


def set_nav_active(widget, button, active):
    """Перекрасить пункт меню: активный залит акцентом."""
    if active:
        button.setStyleSheet(
            f"QPushButton {{ background: {color(widget, 'accent')}; color: white;"
            f" border: none; border-radius: 6px; padding: 6px 12px;"
            f" text-align: left; font-weight: bold; }}")
    else:
        button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {color(widget, 'text')};"
            f" border: none; border-radius: 6px; padding: 6px 12px; text-align: left; }}"
            f"QPushButton:hover {{ background: {color(widget, 'line')}; }}"
            f"QPushButton:disabled {{ color: {color(widget, 'muted')}; }}")


def style_table(widget, table):
    """Таблица рисуется системным стилем и по умолчанию остаётся белой даже
    в тёмной теме — белое пятно посреди окна. Приводим к общему виду."""
    table.setObjectName("grid")
    table.setShowGrid(True)          # линии между столбцами: так строки читаются
    table.setAlternatingRowColors(True)
    table.verticalHeader().setDefaultSectionSize(28)
    table.setStyleSheet(
        f"#grid {{ background: {color(widget, 'panel')};"
        f" gridline-color: {color(widget, 'line')};"
        f" alternate-background-color: {color(widget, 'line')};"
        f" color: {color(widget, 'text')};"
        f" border: 1px solid {color(widget, 'line')}; border-radius: 6px; }}"
        f"#grid::item {{ padding: 4px 6px; border: none; }}"
        f"#grid::item:selected {{ background: {color(widget, 'accent')}; color: white; }}"
        f"QHeaderView::section {{ background: {color(widget, 'panel')};"
        f" color: {color(widget, 'muted')}; border: none;"
        f" border-bottom: 1px solid {color(widget, 'line')}; padding: 6px; }}"
        f"QTableCornerButton::section {{ background: {color(widget, 'panel')};"
        f" border: none; }}")


def app_icon():
    """Иконка окна. Если файла нет — None, и окно останется со стандартной."""
    path = paths.icon_file()
    return QIcon(path) if os.path.exists(path) else None


def logo_label(widget, size=32):
    """Небольшой значок для интерфейса. Нет файла — нет и значка:
    пустой рамки на его месте быть не должно."""
    path = paths.logo_file()
    if not os.path.exists(path):
        return None
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    label = QLabel()
    label.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation))
    label.setFixedSize(size, size)
    return label


# Qt на Windows считает «системным моноширинным» Courier New — шрифт из
# девяностых, с засечками и тонкими штрихами: длинный текст им читать тяжело.
# Поэтому берём первый нормальный из тех, что есть в системе.
MONO_FAMILIES = ("Cascadia Mono", "Consolas", "Segoe UI Mono",
                 "DejaVu Sans Mono", "Courier New")


def mono_font():
    """Моноширинный шрифт для журнала и текста фильтра. Размер тот же, что
    у остального текста: читаемость важнее компактности."""
    available = set(QFontDatabase.families())
    family = next((name for name in MONO_FAMILIES if name in available), None)
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    if family:
        font.setFamily(family)
    font.setPointSize(max(8, QApplication.font().pointSize()))
    return font


def console_box(widget):
    """Окно журнала проверки: моноширинный шрифт, иначе колонки разъезжаются."""
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setMaximumBlockCount(2000)
    box.setFont(mono_font())
    box.setObjectName("console")
    box.setStyleSheet(
        f"#console {{ background: {color(widget, 'panel')};"
        f" border: 1px solid {color(widget, 'line')}; border-radius: 6px;"
        f" padding: 6px; }}")
    return box


def thin_progress(widget):
    """Тонкая полоса без надписи поверх заливки: белый текст на синем
    читается в тёмной теме и теряется в светлой. Подпись идёт рядом."""
    bar = QProgressBar()
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setObjectName("bar")
    bar.setStyleSheet(
        f"#bar {{ border: none; border-radius: 4px;"
        f" background: {color(widget, 'line')}; }}"
        f"#bar::chunk {{ background: {color(widget, 'accent')}; border-radius: 4px; }}")
    return bar
