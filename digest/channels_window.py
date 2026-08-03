"""Таблица каналов: что читает дайджест.

Три вещи, ради которых экран и нужен:
  - ссылка проверяется сразу при добавлении, а не на первом прогоне;
  - видно, у каких каналов уже запомнен id, а у каких ещё нет: только
    запомненные переживут смену ника без потери курсора;
  - переименованный канал не правится молча. Программа показывает новую
    ссылку и ждёт, пока человек нажмёт «Обновить ссылку».
"""
import json
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import ui
from core import channels as links, paths, settings
from core.logs import logger

COL_ON, COL_LINK, COL_NICK, COL_TITLE, COL_STATE = range(5)
IDS_KEY = "__ids__"
SENT_KEY = "__sent__"

# Длинное название режем: в строку таблицы оно всё равно не влезет, а узнать
# канал человеку хватает и начала. Полное остаётся в подсказке при наведении.
TITLE_LIMIT = 40


def read_state():
    """Состояние прогона. Окно читает его целиком, а пишет ровно одно поле —
    название канала, см. save_titles."""
    try:
        with open(paths.state_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_titles(found):
    """Запомнить названия каналов: {ссылка: название}. Вернуть, сколько записали.

    Единственное место, где окно пишет в state.json, и трогает оно там только
    поле title внутри памяти по каналам. Закладки и реестр отправленного не
    задеваются: файл читается целиком и целиком же перезаписывается заново.

    Почему это безопасно: разделы окна выключены, пока идёт проверка, а второй
    экземпляр программы не запускается вовсе — значит писать в файл в этот
    момент больше некому.

    Почему вообще нужно: названия узнаёт прогон, но человек может открыть
    «Каналы» до первой настоящей проверки. Без записи название, найденное
    кнопкой «Проверить все», пропадало бы при следующем открытии страницы.
    """
    if not found:
        return 0
    state = read_state()
    if not state:
        return 0                      # состояния ещё нет — записывать некуда
    ids = state.setdefault(IDS_KEY, {})
    changed = 0
    for link, title in found.items():
        title = str(title or "").strip()
        if not title:
            continue
        nick = links.link_nick(link)
        memo = ids.get(nick)
        if not isinstance(memo, dict):
            # канал только что добавлен, id ещё не запомнен: заводим запись
            # с одним названием. Прогон потом допишет в неё id и ключ.
            memo = {}
            ids[nick] = memo
        if memo.get("title") == title:
            continue
        memo["title"] = title
        changed += 1
    if not changed:
        return 0
    path = paths.state_file()
    tmp = path + ".tmp"
    try:
        paths.ensure_dirs()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"   [!] Не удалось запомнить названия каналов: {e}")
        return 0
    return changed


def remembered_title(state, link):
    """Название канала, запомненное прошлыми проверками. Пусто — ещё не знаем.

    Запоминает его прогон, в той же записи, что и id канала (см. digest.py,
    _remember_chan). Поэтому у только что добавленного канала названия нет
    до первой настоящей проверки — или до нажатия «Проверить все».
    """
    ids = state.get(IDS_KEY) or {}
    memo = ids.get(links.link_nick(link))
    if not isinstance(memo, dict):
        return ""
    return str(memo.get("title") or "").strip()


def short_title(title):
    """Название для клетки таблицы: длинное обрезаем многоточием."""
    title = str(title or "").strip()
    if len(title) <= TITLE_LIMIT:
        return title
    return title[:TITLE_LIMIT - 1].rstrip() + "…"


def memory_note(state, link):
    """Что программа помнит про канал. Человеку это важнее любых цифр:
    у незапомненного канала смена ника означает лавину дублей."""
    ids = state.get(IDS_KEY) or {}
    memo = ids.get(links.link_nick(link))
    if not isinstance(memo, dict) or not memo.get("id"):
        return "новый — id ещё не запомнен"
    key = memo.get("key")
    if key and state.get(key):
        return "читается, id запомнен"
    return "id запомнен"


class ChannelsWindow(QWidget):
    """Страница каналов внутри главного окна."""

    saved = Signal()
    cancelled = Signal()
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle("Каналы")
        self.resize(760, 560)
        self._new_links = {}      # ссылка -> новая ссылка, найденная проверкой
        self._found_titles = {}   # ссылка -> название, узнанное проверкой
        self._pending = 0         # сколько проверок ещё в работе

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Чтение", "Ссылка на канал", "Ник канала", "Название", "Состояние"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_ON, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_LINK, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_NICK, QHeaderView.ResizeToContents)
        # название тянется вместе со ссылкой: на широком экране пустого места
        # было столько, что читать таблицу приходилось через весь монитор
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        ui.style_table(self, self.table)

        self.new_link = QLineEdit()
        self.new_link.setPlaceholderText("https://t.me/имя_канала или @имя_канала")
        self.new_link.returnPressed.connect(self.add_channel)
        self.add_button = QPushButton("Добавить")
        self.add_button.clicked.connect(self.add_channel)

        add_row = QHBoxLayout()
        add_row.addWidget(self.new_link)
        add_row.addWidget(self.add_button)

        self.remove_button = QPushButton("Удалить выбранный")
        self.remove_button.clicked.connect(self.remove_selected)
        self.check_button = QPushButton("Проверить все")
        self.check_button.clicked.connect(self.check_all)
        self.fix_button = QPushButton("Обновить ссылку")
        self.fix_button.setEnabled(False)
        self.fix_button.setToolTip(
            "Заменит ссылку на новую у каналов, которые сменили имя. "
            "Пока вы не нажмёте, ссылки останутся прежними."
        )
        self.fix_button.clicked.connect(self.apply_new_links)

        tools = QHBoxLayout()
        tools.addWidget(self.remove_button)
        tools.addWidget(self.check_button)
        tools.addWidget(self.fix_button)
        tools.addStretch(1)

        self.message = QLabel()
        self.message.setWordWrap(True)

        save_button = QPushButton("Сохранить")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.cancel)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(cancel_button)
        bottom.addWidget(save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(add_row)
        layout.addLayout(tools)
        layout.addWidget(self.message)
        layout.addLayout(bottom)

        # Окно закрыли — оно должно исчезнуть, а не остаться жить у родителя.
        # Иначе каждое следующее открытие добавляет ещё одного слушателя, и
        # проверку каналов обрабатывают все когда-либо открытые окна разом.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._links = [(worker.channel_checked, self.on_checked),
                       # если проверка сорвалась целиком (нет сети, не выполнен
                       # вход), ответа по каналам не придёт — окно иначе навсегда
                       # осталось бы в «проверяю...»
                       (worker.failed, self.on_worker_failed)]
        for signal, slot in self._links:
            signal.connect(slot)
        self.load_values()

    def closeEvent(self, event):
        """Отписываемся явно: полагаться только на удаление объекта нельзя,
        сигнал может прийти между закрытием и уборкой."""
        for signal, slot in self._links:
            try:
                signal.disconnect(slot)
            except Exception:
                pass          # уборка не должна мешать окну закрыться
        self._links = []
        super().closeEvent(event)

    # ---------- таблица ----------

    def load_values(self):
        try:
            data = settings.load(force=True)
        except settings.SettingsError as e:
            self.show_message(str(e), error=True)
            return
        state = read_state()
        self.table.setRowCount(0)
        for item in data.get("channels") or []:
            if isinstance(item, dict):
                link, enabled = str(item.get("url") or item.get("link") or ""), bool(item.get("enabled", True))
            else:
                link, enabled = str(item), True
            if link.strip():
                self.add_row(link.strip(), enabled, memory_note(state, link),
                             remembered_title(state, link))
        self._saved_snapshot = self.snapshot()
        self.show_message(f"Каналов в списке: {self.table.rowCount()}.")

    def add_row(self, link, enabled=True, state_text="", title=""):
        row = self.table.rowCount()
        self.table.insertRow(row)

        box = QCheckBox()
        box.setChecked(enabled)
        box.setToolTip("Снимите галочку, чтобы временно перестать читать канал, "
                       "не удаляя его из списка.")
        holder = QHBoxLayout()
        holder.addWidget(box)
        holder.setAlignment(Qt.AlignCenter)
        holder.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QWidget
        cell = QWidget()
        cell.setLayout(holder)
        self.table.setCellWidget(row, COL_ON, cell)
        cell.checkbox = box

        self.table.setItem(row, COL_LINK, QTableWidgetItem(link))
        self.table.setItem(row, COL_NICK, QTableWidgetItem(links.link_nick(link)))
        self.set_title(row, title)
        self.table.setItem(row, COL_STATE, QTableWidgetItem(state_text))

    def set_title(self, row, title):
        """Название в клетку: обрезанное, а полное — подсказкой при наведении."""
        title = str(title or "").strip()
        cell = QTableWidgetItem(short_title(title))
        if title:
            cell.setToolTip(title)
        self.table.setItem(row, COL_TITLE, cell)

    def row_title(self, row):
        cell = self.table.item(row, COL_TITLE)
        return cell.toolTip() or cell.text() if cell else ""

    def row_link(self, row):
        item = self.table.item(row, COL_LINK)
        return item.text() if item else ""

    def row_enabled(self, row):
        cell = self.table.cellWidget(row, COL_ON)
        return cell.checkbox.isChecked() if cell is not None else True

    def set_state(self, row, text):
        self.table.setItem(row, COL_STATE, QTableWidgetItem(text))

    def find_row(self, link):
        for row in range(self.table.rowCount()):
            if self.row_link(row) == link:
                return row
        return -1

    # ---------- что делает человек ----------

    def add_channel(self):
        link = self.new_link.text().strip()
        if not link:
            return
        if not links.looks_like_channel(link):
            self.show_message(
                "Не похоже на адрес канала. Нужен вид https://t.me/имя_канала "
                "или @имя_канала: латиница, цифры и подчёркивание, 4–32 знака.",
                error=True)
            return
        for row in range(self.table.rowCount()):
            if links.same_channel(self.row_link(row), link):
                self.show_message(
                    f"Такой канал уже есть в списке: {self.row_link(row)}. "
                    "t.me/имя и @имя — это один канал.", error=True)
                return
        self.add_row(link, True, "проверяю...")
        self.new_link.clear()
        self._pending += 1
        self.show_message("Проверяю, открывается ли канал...")
        self.worker.check_channel(link)

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            self.show_message("Сначала выберите строку в таблице.", error=True)
            return
        names = ", ".join(self.row_link(r) for r in rows[:5])
        answer = QMessageBox.question(
            self, "Удалить канал",
            f"Убрать из списка ({len(rows)}): {names}?\n\n"
            "Память о прочитанном не стирается: вернёте канал — читать начнёт "
            "с того места, где остановились.")
        if answer != QMessageBox.Yes:
            return
        for row in rows:
            self.table.removeRow(row)
        self.show_message(f"Удалено строк: {len(rows)}. Не забудьте «Сохранить».")

    def check_all(self):
        if self.table.rowCount() == 0:
            return
        self.check_button.setEnabled(False)
        self._new_links.clear()
        self._found_titles.clear()
        self.fix_button.setEnabled(False)
        self._pending = self.table.rowCount()
        self.show_message(f"Проверяю {self._pending} каналов, это займёт время...")
        for row in range(self.table.rowCount()):
            self.set_state(row, "проверяю...")
            self.worker.check_channel(self.row_link(row))

    def apply_new_links(self):
        """Меняет ссылки только по явному нажатию: молча править нельзя."""
        changed = 0
        for old, new in self._new_links.items():
            row = self.find_row(old)
            if row >= 0:
                self.table.setItem(row, COL_LINK, QTableWidgetItem(new))
                self.table.setItem(row, COL_NICK, QTableWidgetItem(links.link_nick(new)))
                self.set_state(row, "ссылка обновлена")
                changed += 1
        self._new_links.clear()
        self.fix_button.setEnabled(False)
        self.show_message(f"Ссылок обновлено: {changed}. Нажмите «Сохранить», чтобы записать.")

    def save(self):
        seen, out = set(), []
        for row in range(self.table.rowCount()):
            link = self.row_link(row).strip()
            if not link:
                continue
            nick = links.link_nick(link)
            if nick in seen:
                continue
            seen.add(nick)
            # включённый канал пишем строкой, как было всегда; словарь появляется
            # только у выключенных, чтобы файл не менялся без причины
            out.append(link if self.row_enabled(row) else {"url": link, "enabled": False})
        try:
            data = settings.load(force=True)
            data["channels"] = out
            settings.save(data)
        except (settings.SettingsError, OSError) as e:
            self.show_message(f"Не удалось сохранить: {e}", error=True)
            return
        logger.info(f"Список каналов сохранён: {len(out)}")
        self._saved_snapshot = self.snapshot()
        self.saved.emit()

    # ---------- страница ----------

    def snapshot(self):
        return tuple((self.row_link(r), self.row_enabled(r))
                     for r in range(self.table.rowCount()))

    def has_changes(self):
        return self.snapshot() != self._saved_snapshot

    def page_show(self):
        self.load_values()

    def cancel(self):
        self.load_values()
        self.cancelled.emit()

    # ---------- ответы проверки ----------

    def on_checked(self, link, verdict, detail, title=""):
        row = self.find_row(link)
        self._pending = max(0, self._pending - 1)
        if title:
            self._found_titles[link] = title
        if row >= 0:
            if title:
                self.set_title(row, title)
            if verdict == "ok":
                self.set_state(row, "открывается")
            elif verdict == "renamed":
                self._new_links[link] = detail
                self.set_state(row, f"сменил ссылку → {detail}")
                self.fix_button.setEnabled(True)
            else:
                self.set_state(row, "не открылся")
                self.table.item(row, COL_STATE).setToolTip(detail)
        if self._pending == 0:
            self.check_button.setEnabled(True)
            self.summarize()

    def on_worker_failed(self, text):
        self._pending = 0
        self.check_button.setEnabled(True)
        for row in range(self.table.rowCount()):
            if (self.table.item(row, COL_STATE) or QTableWidgetItem()).text() == "проверяю...":
                self.set_state(row, "проверка не дошла")
        self.show_message(text, error=True)

    def summarize(self):
        # названия запоминаем разом, когда все проверки закончились:
        # писать в файл после каждого из полусотни каналов незачем
        saved = save_titles(self._found_titles)
        if saved:
            logger.info(f"Запомнены названия каналов: {saved}")
        self._found_titles.clear()

        bad = sum(1 for r in range(self.table.rowCount())
                  if (self.table.item(r, COL_STATE) or QTableWidgetItem()).text() == "не открылся")
        if self._new_links:
            self.show_message(
                f"Сменили ссылку: {len(self._new_links)}. Нажмите «Обновить ссылку», "
                "чтобы принять новые адреса.", error=True)
        elif bad:
            self.show_message(f"Не открылись: {bad}. Наведите курсор на «не открылся», "
                              "чтобы увидеть причину.", error=True)
        else:
            self.show_message("Проверка закончена, все каналы открываются.")

    def show_message(self, text, error=False):
        self.message.setStyleSheet(f"color: {self.error_color()};" if error else "")
        self.message.setText(text)

    def error_color(self):
        background = self.palette().color(self.backgroundRole())
        return "#ff8a80" if background.lightness() < 128 else "#b00020"
