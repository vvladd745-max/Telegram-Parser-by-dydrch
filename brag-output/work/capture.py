"""Снимает настоящие окна программы в тёмной теме для ролика.

Песочница: DIGEST_HOME и имя хранилища секретов подменены, боевые файлы
не трогаются. Данные в кадре вымышленные.
"""
import json, os, shutil, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.join(WORK, "home")
SHOTS = os.path.join(WORK, "shots")

os.environ["DIGEST_HOME"] = HOME
os.environ["DIGEST_KEYRING_SERVICE"] = "brag-sandbox"
os.environ["PYTHON_KEYRING_BACKEND"] = "keyrings.alt.file.PlaintextKeyring"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "2"

shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME)
with open(os.path.join(ROOT, "settings.default.json"), encoding="utf-8") as f:
    data = json.load(f)
data["telegram"]["api_id"] = 1234567
data["telegram"]["target"] = -1001234567890
data["ui"]["theme"] = "dark"
data["ui"]["font_size"] = 10
with open(os.path.join(HOME, "settings.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

INTERESTS = """Ты фильтр постов из Telegram-каналов.
Ответь строго одним словом: INTERESTING или SKIP.

ИНТЕРЕСНО:
- новости и обзоры техники, утечки характеристик
- крупные события в играх и киберспорте
- инструкции и разборы, которые можно пересказать

НЕ ИНТЕРЕСНО:
- реклама и промокоды, пометка «erid», #реклама
- розыгрыши и конкурсы
- посты без содержания
"""
with open(os.path.join(HOME, "interests.txt"), "w", encoding="utf-8") as f:
    f.write(INTERESTS)

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "digest"))

from core import secrets  # noqa: E402
secrets.store("telegram.api_hash", "0" * 32)

from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import ui  # noqa: E402

app = QApplication(sys.argv)
app.setFont(QFont("Inter", 10))
ui.MONO_FAMILIES = ("JetBrains Mono",) + ui.MONO_FAMILIES
ui.apply_theme(app, "dark")

import app as appmod  # noqa: E402

win = appmod.MainWindow()
win.resize(1100, 720)
win.telegram.logged_in.disconnect()
win.telegram.status.disconnect()
win.telegram.failed.disconnect()
win.telegram_value.setText("выполнен — Анна")
win.problems_card.setVisible(False)
win.refresh = lambda *a, **k: None
win.problems_card.setVisible(False)
win.channels_value.setText("54")
win.home_value.setText(r"C:\Users\Анна\AppData\Local\TelegramDigest")
win.mode_value.setText("обычный — файлы в папке пользователя")
win.log_value.setText(r"C:\Users\Анна\AppData\Local\TelegramDigest\logs")
win.status.setText("")
win.health = getattr(win, "health", None)
win.show()


def settle():
    for _ in range(20):
        app.processEvents()


def geom(widget):
    p = widget.mapTo(win, widget.rect().topLeft())
    return [p.x(), p.y(), widget.width(), widget.height()]


settle()

# Страница «Проверка», до запуска
win.console.clear()
win.console.set_hint("")
settle()
win.grab().save(os.path.join(SHOTS, "run-empty.png"))

# Идёт проверка: прогресс, счётчики, журнал
win.progress_label.setText("Канал 5 из 54: Код Дурова")
win.progress_label.setVisible(True)
win.progress.setVisible(True)
win.progress.setRange(0, 54)
win.progress.setValue(5)
win.run_button.setEnabled(False)
win.cancel_button.setEnabled(True)
win.dry_run_box.setChecked(False)
for key, val in {"checked": 0, "found": 0, "skipped": 0, "errors": 0}.items():
    win.counter_labels[key].setText(str(val))
settle()
win.grab().save(os.path.join(SHOTS, "run-live.png"))

layout = {
    "window": [0, 0, win.width(), win.height()],
    "console": geom(win.console),
    "counters": {k: geom(v) for k, v in win.counter_labels.items()},
    "progress": geom(win.progress),
    "progress_label": geom(win.progress_label),
    "run_button": geom(win.run_button),
    "scale": 2,
}

# Остальные страницы
for page, name in ((appmod.PAGE_CHANNELS, "channels"),
                   (appmod.PAGE_INTERESTS, "interests"),
                   (appmod.PAGE_SCHEDULE, "schedule")):
    win.go_to(page, force=True)
    settle()
    win.grab().save(os.path.join(SHOTS, f"{name}.png"))

with open(os.path.join(SHOTS, "layout.json"), "w") as f:
    json.dump(layout, f, indent=2)
print(json.dumps(layout))
os._exit(0)
