"""Страница «Расписание»: во сколько и по каким дням проверять каналы.

Само расписание держит Планировщик заданий Windows — см. core/schedule.py.
Здесь только окно: показать, что настроено, и попросить планировщик это
запомнить. Настройки и планировщик расходятся легко (задачу можно удалить
руками через «Планировщик заданий»), поэтому страница каждый раз спрашивает
у планировщика, на месте ли задача, и говорит об этом прямо.

Чего здесь намеренно нет — выбора «тестовая или настоящая». По расписанию
проверка всегда настоящая: тестовая ничего не пересылает, и запускать её
по утрам не имеет смысла.
"""
from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QTimeEdit,
    QVBoxLayout, QWidget,
)

import ui
from core import schedule, settings
from core.logs import logger

HEAD_TEXT = (
    "Программа может проверять каналы сама, без вашего участия. В назначенный "
    "час Windows откроет её и сразу запустит настоящую проверку: отобранные "
    "посты уйдут в ваш канал, закладки сдвинутся.\n\n"
    "Если в это время компьютер был выключен или спал, проверка не пропадёт — "
    "она начнётся, как только вы его включите."
)

WARN_TEXT = (
    "Две вещи, о которых лучше знать заранее.\n\n"
    "Окно после проверки остаётся открытым — чтобы вы видели, что нашлось. "
    "Пока оно открыто, следующая проверка по расписанию не начнётся: двум "
    "копиям программы разом работать нельзя. Закрывайте окно, когда посмотрели.\n\n"
    "Проверка отбирает посты локальной моделью, поэтому к назначенному часу "
    "должен быть запущен LM Studio с загруженной моделью. Если его нет, "
    "проверка не начнётся и ничего не потеряет: закладки останутся на месте."
)


class ScheduleWindow(QWidget):
    """Страница расписания внутри главного окна."""

    saved = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(ui.label(HEAD_TEXT, wrap=True))

        # --- когда ---
        self.enabled_box = QCheckBox("Проверять по расписанию")
        self.enabled_box.toggled.connect(self._sync_enabled)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setToolTip("Час и минуты, когда начинать проверку.")
        self.time_edit.timeChanged.connect(self._sync_preview)

        self.day_boxes = {}
        days_row = QHBoxLayout()
        days_row.setSpacing(10)
        for key, _, name in schedule.DAYS:
            box = QCheckBox(name)
            box.toggled.connect(self._sync_preview)
            self.day_boxes[key] = box
            days_row.addWidget(box)
        days_row.addStretch(1)

        every_day = QPushButton("Каждый день")
        every_day.clicked.connect(lambda: self._set_days(schedule.ALL_DAYS))
        weekdays = QPushButton("Только будни")
        weekdays.clicked.connect(lambda: self._set_days(schedule.DAY_KEYS[:5]))
        quick = QHBoxLayout()
        quick.addWidget(every_day)
        quick.addWidget(weekdays)
        quick.addStretch(1)

        when = QFormLayout()
        when.setHorizontalSpacing(16)
        when.setVerticalSpacing(10)
        when.addRow("", self.enabled_box)
        when.addRow("Во сколько", self.time_edit)
        when.addRow("По каким дням", days_row)
        when.addRow("", quick)
        layout.addWidget(ui.card(self, "Когда проверять", when))

        # --- что из этого выходит ---
        self.preview = ui.label(wrap=True)
        self.task_state = ui.label(wrap=True, tone="muted", widget=self)
        state = QVBoxLayout()
        state.setSpacing(6)
        state.addWidget(self.preview)
        state.addWidget(self.task_state)
        layout.addWidget(ui.card(self, "Что будет", state))

        # Это предупреждение человек должен прочитать, а не выуживать из
        # всплывающей подсказки: обе вещи объясняют, почему проверки может
        # не случиться, и обе неочевидны.
        warn = QVBoxLayout()
        warn.addWidget(ui.label(WARN_TEXT, tone="muted", widget=self, wrap=True))
        layout.addWidget(ui.card(self, "О чём стоит знать", warn))
        layout.addStretch(1)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message)

        save_button = QPushButton("Сохранить")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.cancel)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(cancel_button)
        bottom.addWidget(save_button)
        layout.addLayout(bottom)

        self.load_values()

    # ---------- чтение и запись ----------

    def load_values(self):
        """Заполнить страницу тем, что записано в настройках."""
        enabled, time_text, days = schedule.current()
        hour, minute = schedule.parse_time(time_text)
        self.enabled_box.setChecked(enabled)
        self.time_edit.setTime(QTime(hour, minute))
        for key, box in self.day_boxes.items():
            box.setChecked(key in days)
        self._saved_values = self._values()
        self.show_message("")
        self._sync_enabled(enabled)

    def _values(self):
        time_text = self.time_edit.time().toString("HH:mm")
        days = [key for key, box in self.day_boxes.items() if box.isChecked()]
        return self.enabled_box.isChecked(), time_text, schedule.clean_days(days)

    def save(self):
        enabled, time_text, days = self._values()
        if enabled and not days:
            self.show_message(
                "Не выбрано ни одного дня недели — проверять нечего и некогда. "
                "Отметьте хотя бы один день.", error=True)
            return

        # Сначала планировщик, потом файл настроек. Если планировщик откажет,
        # в настройках не должно остаться расписания, которого на самом деле нет.
        try:
            outcome = schedule.sync(enabled, time_text, days)
        except schedule.ScheduleError as e:
            self.show_message(str(e), error=True)
            return

        try:
            data = settings.load(force=True)
        except settings.SettingsError as e:
            self.show_message(str(e), error=True)
            return
        data.setdefault("schedule", {})
        data["schedule"]["enabled"] = enabled
        data["schedule"]["time"] = time_text
        data["schedule"]["days"] = days
        try:
            settings.save(data)
        except OSError as e:
            self.show_message(f"Не удалось записать настройки: {e}", error=True)
            return

        logger.info(f"Расписание сохранено: включено={enabled}, {time_text}, "
                    f"{schedule.days_text(days)}")
        self._saved_values = self._values()
        self.show_message(outcome)
        self.saved.emit()

    # ---------- страница ----------

    def has_changes(self):
        return self._values() != self._saved_values

    def page_show(self):
        self.load_values()

    def cancel(self):
        self.load_values()
        self.cancelled.emit()

    # ---------- мелочи ----------

    def _set_days(self, keys):
        chosen = set(keys)
        for key, box in self.day_boxes.items():
            box.setChecked(key in chosen)

    def _sync_enabled(self, enabled):
        """Поля времени и дней имеют смысл, только когда расписание включено."""
        for widget in [self.time_edit] + list(self.day_boxes.values()):
            widget.setEnabled(bool(enabled))
        self._sync_preview()

    def _sync_preview(self):
        """Строка «что будет» — прямо под настройками, до всякого сохранения."""
        enabled, time_text, days = self._values()
        if not enabled:
            self.preview.setText("Проверка по расписанию выключена — "
                                 "программа запускается только вручную.")
        elif not days:
            self.preview.setText("Не выбрано ни одного дня — проверка не запустится ни разу.")
        else:
            self.preview.setText(
                f"Проверка {schedule.days_text(days)} в {time_text}. "
                f"Ближайшая — {schedule.next_run_text(time_text, days)}.")

        # у планировщика спрашиваем отдельно: настройки и он расходятся,
        # если задачу убрали руками через «Планировщик заданий»
        exists = schedule.installed()
        if exists and not enabled:
            self.task_state.setText(
                "Задача в Планировщике Windows пока есть — она уйдёт, "
                "когда вы нажмёте «Сохранить».")
        elif enabled and not exists:
            self.task_state.setText(
                "Задача в Планировщике Windows ещё не создана — "
                "она появится после «Сохранить».")
        elif exists:
            self.task_state.setText("Задача в Планировщике Windows на месте.")
        else:
            self.task_state.setText("")

    def show_message(self, text, error=False):
        self.message.setStyleSheet(f"color: {ui.color(self, 'bad')};" if error else "")
        self.message.setText(text)
