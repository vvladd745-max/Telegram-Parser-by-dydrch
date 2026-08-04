"""Страница «О программе»: что это, версия и куда писать.

Ссылки заполняются здесь, в LINKS, а не в настройках: их правит тот, кто
собирает программу, а не тот, кто ей пользуется. Пустая ссылка не ломает
страницу — на её месте появляется серая пометка, что адрес пока не указан.
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import ui
from core import paths

APP_VERSION = "1.1"

# --- Сюда вписываются адреса. Пустая строка не ломает страницу. ---
LINKS = [
    ("Исходный код", "https://github.com/vvladd745-max/Telegram-Parser-by-dydrch",
     "Страница проекта на GitHub: код, установщик и список изменений."),
    ("Канал программы", "https://t.me/tg_parser_by_dydrch",
     "Новости о программе: что нового, что исправлено."),
    ("Автор", "https://t.me/dydrch_kanava", "Личный канал автора."),
]

DESCRIPTION = (
    "Программа читает Telegram-каналы, показывает каждый новый пост локальной "
    "ИИ-модели и пересылает вам только то, что подходит под ваше описание "
    "интересов. Ничего не уходит в интернет: модель работает на вашем "
    "компьютере, а посты пересылаются в ваш собственный приватный канал."
)


def link_label(widget, url, description):
    """Строка со ссылкой. Пустой адрес — серая пометка вместо ссылки."""
    if url:
        label = QLabel(f'<a href="{url}">{url}</a>')
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    else:
        label = ui.label("адрес пока не указан", tone="muted", widget=widget)
    label.setToolTip(description)
    label.setWordWrap(True)
    return label


class AboutPage(QWidget):
    """Страница только читается — ничего не сохраняет и ничего не спрашивает."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        logo = ui.logo_label(self, size=64)
        if logo is not None:
            title_row.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(ui.label("Парсер Telegram-каналов", size=15, bold=True))
        names.addWidget(ui.label(f"версия {APP_VERSION}", tone="muted", widget=self))
        title_row.addLayout(names)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        about = QVBoxLayout()
        about.addWidget(ui.label(DESCRIPTION, wrap=True))
        layout.addWidget(ui.card(self, "Что это", about))

        contacts = QFormLayout()
        contacts.setHorizontalSpacing(16)
        contacts.setVerticalSpacing(8)
        for name, url, description in LINKS:
            contacts.addRow(ui.label(name, tone="muted", widget=self),
                            link_label(self, url, description))
        layout.addWidget(ui.card(self, "Контакты", contacts))

        where = QFormLayout()
        where.setHorizontalSpacing(16)
        where.setVerticalSpacing(8)
        where.addRow(ui.label("Папка с данными", tone="muted", widget=self),
                     ui.label(paths.home(), wrap=True, selectable=True))
        where.addRow(ui.label("Журнал", tone="muted", widget=self),
                     ui.label(paths.logs_dir(), wrap=True, selectable=True))
        where.addRow(ui.label("Модель", tone="muted", widget=self),
                     ui.label("LM Studio на этом компьютере", wrap=True))
        layout.addWidget(ui.card(self, "Где что лежит", where))

        layout.addStretch(1)
        layout.addWidget(ui.label(
            "Если что-то не работает, пришлите файл журнала из папки выше — "
            "по нему видно, на чём программа споткнулась.",
            tone="muted", widget=self, wrap=True))
