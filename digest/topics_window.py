"""Окно со списком направлений сео-поиска.

Отдельное окно, а не страница в боковом меню: сюда заходят редко и ненадолго,
а места оно занимает много — два списка рядом.

Устройство простое: слева направления, справа запросы выбранного направления.
Правки копятся в памяти и уходят на диск только по кнопке «Сохранить» —
так неудачную возню всегда можно отменить целиком.

Чего окно НЕ трогает:

  id направления — по нему сео-поиск узнаёт свои кэш и квоты. У готовых
  направлений он остаётся прежним навсегда, новым выдаётся свой.

  cursor — метка ротации: за прогон берётся несколько направлений по кругу.
  Сео-поиск берёт её по остатку от числа направлений, поэтому устареть она
  не может. А вот пустой список уронил бы деление на ноль — поэтому удалить
  все направления окно не даёт.
"""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

import ui
from core import seeds as fresh, spheres
from core.logs import logger

# Первая строка в списке направлений — не направление из файла, а то, что
# проверка каналов насобирала сама. Стоит сверху нарочно: это единственное,
# что меняется само по себе, и смотреть туда хочется первым делом.
FRESH_TITLE = "Найденное в Telegram"

FRESH_NOTE = (
    "Это программа собрала сама из постов, которые сочла интересными. "
    "Править список нельзя: он обновляется каждой настоящей проверкой. "
    "Сео-поиск берёт отсюда до 12 самых свежих фраз не старше 10 дней "
    "и ищет по ним наравне с обычными направлениями."
)

FRESH_EMPTY = (
    "Пока пусто. Список наполняется НАСТОЯЩИМИ проверками — в тестовых "
    "программа до этого шага не доходит. Пройдёт первая настоящая проверка "
    "с интересными постами — здесь появятся фразы."
)

HEAD = (
    "Направление — это тема, по которой сео-поиск ищет, что люди спрашивают "
    "в поисковиках. Запросы внутри направления — те слова, с которых он "
    "начинает: по ним подбираются похожие, а из них уже отбираются темы "
    "для статей.\n\n"
    "За один прогон берётся несколько направлений подряд, по кругу, — так "
    "за неделю обходятся все."
)

TIP_BLOCKS = ('Список тем, по которым идёт поиск.\n\nЗа один прогон берётся не весь '
              'список, а несколько направлений подряд — дальше очередь сдвигается,\n'
              'и в следующий раз возьмутся следующие. Так за несколько дней\n'
              'обходятся все направления.\n\nДвойной щелчок по названию — переименовать.')

TIP_SEEDS = ('Слова, с которых начинается поиск по этому направлению.\n\nПишите так, '
             'как спрашивают в поисковике: «как настроить роутер», «windows 11».\n'
             'По каждому такому запросу подбираются похожие, и уже из них\n'
             'отбираются темы для статей.\n\nДвойной щелчок по запросу — исправить.')


class TopicsWindow(QDialog):
    """Список направлений сео-поиска. Открывается кнопкой из «Настроек»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Направления сео-поиска")
        self.setMinimumSize(760, 520)

        self.data = None          # рабочая копия, правится в памяти
        self.saved = None         # то, что лежит на диске: с чем сравниваем

        # --- левый столбец: направления ---
        self.blocks = QListWidget()
        self.blocks.currentRowChanged.connect(self.on_block_changed)
        self.blocks.itemChanged.connect(self.on_block_renamed)

        add_block = QPushButton("Добавить")
        add_block.clicked.connect(self.add_block)
        del_block = QPushButton("Удалить")
        del_block.clicked.connect(self.remove_block)

        blocks_buttons = QHBoxLayout()
        blocks_buttons.addWidget(add_block)
        blocks_buttons.addWidget(del_block)
        blocks_buttons.addStretch(1)

        blocks_inner = QVBoxLayout()
        blocks_inner.addWidget(self.blocks)
        blocks_inner.addLayout(blocks_buttons)
        blocks_card = ui.card(self, "Направления", blocks_inner)

        # --- правый столбец: запросы выбранного направления ---
        self.seeds = QListWidget()
        self.seeds.itemChanged.connect(self.on_seed_edited)

        # Пояснение показывается только для «Найденного в Telegram»: у обычных
        # направлений оно было бы пустой строкой, съедающей место.
        self.fresh_note = ui.label("", tone="muted", widget=self, wrap=True)
        self.fresh_note.setVisible(False)

        self.add_seed_button = QPushButton("Добавить")
        self.add_seed_button.clicked.connect(self.add_seed)
        self.del_seed_button = QPushButton("Удалить")
        self.del_seed_button.clicked.connect(self.remove_seed)

        seeds_buttons = QHBoxLayout()
        seeds_buttons.addWidget(self.add_seed_button)
        seeds_buttons.addWidget(self.del_seed_button)
        seeds_buttons.addStretch(1)

        seeds_inner = QVBoxLayout()
        seeds_inner.addWidget(self.fresh_note)
        seeds_inner.addWidget(self.seeds)
        seeds_inner.addLayout(seeds_buttons)
        self.seeds_card = ui.card(self, "Запросы направления", seeds_inner)

        columns = QHBoxLayout()
        columns.addWidget(blocks_card, 2)
        columns.addWidget(self.seeds_card, 3)

        # --- подсказки и низ окна ---
        tips = QHBoxLayout()
        tips.addWidget(ui.label("Что это такое:", tone="muted", widget=self))
        tips.addWidget(ui.hint(self, TIP_BLOCKS))
        tips.addWidget(ui.label("направления", tone="muted", widget=self))
        tips.addWidget(ui.hint(self, TIP_SEEDS))
        tips.addWidget(ui.label("запросы", tone="muted", widget=self))
        tips.addStretch(1)

        self.message = ui.label("", tone="muted", widget=self, wrap=True)

        save_button = QPushButton("Сохранить")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.close)

        bottom = QHBoxLayout()
        bottom.addWidget(self.message, 1)
        bottom.addWidget(close_button)
        bottom.addWidget(save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(ui.label(HEAD, tone="muted", widget=self, wrap=True))
        layout.addLayout(columns)
        layout.addLayout(tips)
        layout.addLayout(bottom)

        self.load_values()

    # ---------- чтение ----------

    def load_values(self):
        data = spheres.load()
        if data is None:
            self.data = {"cursor": 0, "blocks": []}
            self.show_message("Списка направлений пока нет — добавьте первое.",
                              error=True)
        else:
            self.data = data
        self.data.setdefault("blocks", [])
        self.data.setdefault("cursor", 0)
        self.saved = copy.deepcopy(self.data)
        self.fill_blocks()

    def fill_blocks(self, select=0):
        """Наполняет левый список. Первой строкой всегда «Найденное в Telegram»,
        поэтому направление под номером N живёт в строке N+1."""
        # Пока наполняем список, itemChanged срабатывает на каждой строке.
        # Без этой заглушки первая же вставка переименовала бы чужое направление.
        self.blocks.blockSignals(True)
        self.blocks.clear()
        head = QListWidgetItem(FRESH_TITLE)
        # переименовать его нельзя: это не строка из файла, а живой список
        head.setFlags(head.flags() & ~Qt.ItemIsEditable)
        self.blocks.addItem(head)
        for block in self.data["blocks"]:
            item = QListWidgetItem(str(block.get("name") or block.get("id") or ""))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.blocks.addItem(item)
        self.blocks.blockSignals(False)
        self.blocks.setCurrentRow(min(select, self.blocks.count() - 1))
        self.on_block_changed(self.blocks.currentRow())

    def fill_seeds(self, block):
        self.fresh_note.setVisible(False)
        self.seeds.blockSignals(True)
        self.seeds.clear()
        if block is not None:
            for seed in block.get("seeds", []):
                item = QListWidgetItem(str(seed))
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                self.seeds.addItem(item)
        self.seeds.blockSignals(False)
        self.seeds.setEnabled(block is not None)
        self.add_seed_button.setEnabled(block is not None)
        self.del_seed_button.setEnabled(block is not None)

    def fill_fresh(self):
        """Показывает то, что проверка каналов насобирала сама.

        Ровно то же, что возьмёт сео-поиск: свежие фразы, не старше десяти
        дней. Список только для чтения — его пишет проверка, а не человек.
        """
        self.seeds.blockSignals(True)
        self.seeds.clear()
        try:
            phrases = fresh.load_fresh_seeds()
            total = fresh.stored_count()
        except Exception as e:
            phrases, total = [], 0
            logger.warning(f"   [!] не смог прочитать найденное в Telegram: {e}")
        for phrase in phrases:
            item = QListWidgetItem(str(phrase))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.seeds.addItem(item)
        self.seeds.blockSignals(False)
        self.seeds.setEnabled(True)
        # править нечего: список живёт своей жизнью
        self.add_seed_button.setEnabled(False)
        self.del_seed_button.setEnabled(False)
        if phrases:
            self.fresh_note.setText(
                f"{FRESH_NOTE}\n\nСейчас в запасе {total}, из них свежих — {len(phrases)}.")
        else:
            self.fresh_note.setText(FRESH_EMPTY)
        self.fresh_note.setVisible(True)

    def current_block(self):
        """Направление под курсором. None — если выбрано «Найденное в Telegram»."""
        row = self.blocks.currentRow() - 1        # первая строка не из файла
        if 0 <= row < len(self.data["blocks"]):
            return self.data["blocks"][row]
        return None

    # ---------- правки ----------

    def on_block_changed(self, row):
        if row == 0:
            self.fill_fresh()
        else:
            self.fill_seeds(self.current_block())

    def on_block_renamed(self, item):
        block = self.current_block()
        if block is None:
            return
        name = item.text().strip()
        if not name:
            # Пустое имя не принимаем: в списке осталась бы пустая строка,
            # и человек не понял бы, что это за направление.
            item.setText(str(block.get("name") or ""))
            self.show_message("У направления должно быть название.", error=True)
            return
        block["name"] = name
        self.show_message("")

    def on_seed_edited(self, item):
        block = self.current_block()
        if block is None:
            return
        text = item.text().strip()
        row = self.seeds.row(item)
        seeds = block.setdefault("seeds", [])
        if not text:
            # Пустой запрос убираем сразу: сохранять его незачем, а искать
            # по пустоте нечего.
            seeds.pop(row) if row < len(seeds) else None
            self.fill_seeds(block)
            return
        if row < len(seeds):
            seeds[row] = text
        else:
            seeds.append(text)
        self.show_message("")

    def add_block(self):
        name = "Новое направление"
        block = {"id": spheres.new_id(self.data["blocks"], name),
                 "name": name, "seeds": []}
        self.data["blocks"].append(block)
        self.fill_blocks(select=len(self.data["blocks"]))   # +1 на первую строку
        # сразу отдаём название в правку: имя по умолчанию всё равно менять
        self.blocks.editItem(self.blocks.currentItem())
        self.show_message("Впишите название, потом добавьте запросы справа.")

    def remove_block(self):
        if self.blocks.currentRow() == 0:
            self.show_message("«Найденное в Telegram» удалить нельзя: этот список "
                              "программа ведёт сама.", error=True)
            return
        row = self.blocks.currentRow() - 1
        if not (0 <= row < len(self.data["blocks"])):
            return
        if len(self.data["blocks"]) == 1:
            self.show_message("Это последнее направление — без единого сео-поиску "
                              "нечего делать.", error=True)
            return
        block = self.data["blocks"][row]
        answer = QMessageBox.question(
            self, "Удалить направление",
            f"Удалить «{block.get('name')}» и все его запросы?")
        if answer != QMessageBox.Yes:
            return
        self.data["blocks"].pop(row)
        self.fill_blocks(select=row + 1)      # +1: первая строка не из файла
        self.show_message("Удалено. Пока не нажали «Сохранить», можно закрыть "
                          "окно и всё останется как было.")

    def add_seed(self):
        block = self.current_block()
        if block is None:
            self.show_message("Сначала выберите направление слева.", error=True)
            return
        block.setdefault("seeds", []).append("новый запрос")
        self.fill_seeds(block)
        self.seeds.setCurrentRow(len(block["seeds"]) - 1)
        self.seeds.editItem(self.seeds.currentItem())

    def remove_seed(self):
        block = self.current_block()
        row = self.seeds.currentRow()
        if block is None or not (0 <= row < len(block.get("seeds", []))):
            return
        block["seeds"].pop(row)
        self.fill_seeds(block)
        self.seeds.setCurrentRow(min(row, len(block["seeds"]) - 1))

    # ---------- сохранение ----------

    def troubles(self):
        """Что мешает сохранить. Пусто — значит всё в порядке."""
        blocks = self.data["blocks"]
        if not blocks:
            return ["Не осталось ни одного направления — сео-поиску нечего делать."]
        out = []
        for block in blocks:
            name = str(block.get("name") or "").strip()
            if not name:
                out.append("У одного из направлений пустое название.")
            elif not [s for s in block.get("seeds", []) if str(s).strip()]:
                out.append(f"У направления «{name}» нет ни одного запроса.")
        return out

    def save(self):
        troubles = self.troubles()
        if troubles:
            self.show_message(" ".join(troubles[:2]), error=True)
            return
        # чистим на пороге: лишние пробелы и пустые строки на диск не нужны
        for block in self.data["blocks"]:
            block["name"] = str(block["name"]).strip()
            block["seeds"] = [str(s).strip() for s in block.get("seeds", [])
                              if str(s).strip()]
        try:
            spheres.save(self.data)
        except OSError as e:
            self.show_message(f"Не удалось записать список направлений: {e}",
                              error=True)
            return
        self.saved = copy.deepcopy(self.data)
        total = sum(len(b["seeds"]) for b in self.data["blocks"])
        logger.info(f"Направления сео-поиска сохранены из окна: "
                    f"{len(self.data['blocks'])} шт., запросов {total}.")
        self.show_message(f"Сохранено: направлений {len(self.data['blocks'])}, "
                          f"запросов {total}.")

    def has_changes(self):
        return self.data != self.saved

    def closeEvent(self, event):
        if self.has_changes():
            answer = QMessageBox.question(
                self, "Несохранённые правки",
                "Правки в списке направлений не сохранены. Закрыть и потерять их?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    # ---------- мелочи ----------

    def show_message(self, text, error=False):
        self.message.setText(text)
        tone = "bad" if error else "muted"
        self.message.setStyleSheet(f"color: {ui.color(self, tone)};")


def show_topics(parent):
    """Открыть окно направлений. Зовётся из «Настроек»."""
    window = TopicsWindow(parent)
    window.exec()
