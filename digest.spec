# Описание сборки для PyInstaller. Собирать так:
#     pyinstaller digest.spec --noconfirm
# Результат: dist/Парсер Telegram-каналов/ — папка целиком, её и кладём в установщик.
#
# Почему --onedir, а не один файл: onefile каждый запуск распаковывает всё
# во временную папку, это медленно и мешает антивирусам. Решение принято
# в docs/roadmap.md.
import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.getcwd())

# Заготовки, которые едут вместе с программой. Личных данных в них нет:
# settings.default.json — без api_id, api_hash, токена бота и chat_id.
DATA = [
    (os.path.join(ROOT, "settings.default.json"), "."),
    (os.path.join(ROOT, "interests.default.txt"), "."),
]
# Картинки кладём, только если они есть: без них программа работает,
# просто со стандартной иконкой Windows.
for picture in ("icon.ico", "logo.png"):
    if os.path.exists(os.path.join(ROOT, picture)):
        DATA.append((os.path.join(ROOT, picture), "."))

ICON = os.path.join(ROOT, "icon.ico")
ICON = ICON if os.path.exists(ICON) else None

HIDDEN = [
    # digest.py импортируется на ходу, из потока прогона: анализатор
    # PyInstaller такой импорт не видит и модуль в сборку не кладёт
    "digest",
    # backend хранилища секретов подключается по имени во время работы.
    # Без него keyring в сборке молча «не находит» ключи, и программа
    # решает, что api_hash не заполнен.
    "keyring.backends.Windows",
    "win32ctypes.core",
    "win32ctypes.core.ctypes",
    # Поиск тем лежит ОТДЕЛЬНОЙ папкой рядом с программой, а не внутри сборки:
    # так его можно положить себе и не отдать коллегам вместе с установщиком.
    # Раз его нет в сборке, анализатор не видит и того, что он импортирует, —
    # эти два модуля приходится называть руками, иначе поиск тем в собранной
    # программе упадёт на первой же строке.
    "csv",
    "math",
    # Прокси для Telethon. Он импортирует python_socks внутри функции,
    # а нужные куски тот подтягивает по имени уже на ходу — анализатор
    # такого не видит, и в сборке прокси молча не работал бы.
] + collect_submodules("python_socks") + collect_submodules("win32ctypes")

a = Analysis(
    [os.path.join(ROOT, "digest", "app.py")],
    pathex=[ROOT, os.path.join(ROOT, "digest")],
    binaries=[],
    datas=DATA,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    # тяжёлое и ненужное: тянется за PySide6 и раздувает папку
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
              "matplotlib", "numpy", "PIL",
              # aiohttp у Telethon необязателен (там try/except ImportError) и
              # нужен только для скачивания веб-документов, чего мы не делаем.
              # А при импорте он строит SSL-контекст из хранилища сертификатов
              # Windows и в собранном виде на этом падает ещё до нашего кода.
              "aiohttp"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Парсер Telegram-каналов",
    debug=False,
    strip=False,
    upx=False,
    # Обычная сборка — без консоли (на этом и падал старый logs.py).
    # Для разбора поломок: DIGEST_BUILD_CONSOLE=1 pyinstaller digest.spec
    console=bool(os.environ.get("DIGEST_BUILD_CONSOLE")),
    disable_windowed_traceback=False,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Парсер Telegram-каналов",
)
