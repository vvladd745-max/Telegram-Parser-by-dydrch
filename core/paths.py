"""Единственное место в проекте, которое знает, где лежат файлы пользователя.

Ни один другой модуль не должен собирать пути сам: если завтра папка данных
переедет, править надо будет только здесь.

Корень данных выбирается по трём правилам, строго в этом порядке:
  1) переменная окружения DIGEST_HOME — ручное переопределение, побеждает всё;
  2) портативный режим: рядом с программой уже лежит settings.json — значит
     её запускают из своей папки, и файлы должны остаться там же, где были.
     «Рядом с программой» — это папка с .exe в сборке и корень проекта при
     запуске из исходников, см. app_dir();
  3) обычный режим: platformdirs подсказывает папку данных пользователя
     (%LOCALAPPDATA%\\TelegramDigest). Это путь для коллег: у них будет
     установленная программа, а не папка с кодом.

Рабочие файлы дайджеста (состояние, сессия, лок) лежат в подпапке digest/
во всех режимах. В портативном это ровно та же digest/ рядом с кодом,
где они лежали всегда, — ничего никуда не переезжает.
"""
import os
import sys

from platformdirs import user_data_dir

from . import config

APP_NAME = "TelegramDigest"

SETTINGS_NAME = "settings.json"
SETTINGS_TEMPLATE_NAME = "settings.default.json"
INTERESTS_NAME = "interests.txt"
# Шаблон отдельным файлом, а не тем же самым: раньше в портативном режиме
# заготовка и рабочий файл совпадали, и «вернуть шаблон» было нечем.
INTERESTS_TEMPLATE_NAME = "interests.default.txt"
# Картинки едут вместе с программой: .ico для окна и .exe, .png для
# самого интерфейса. Их может не быть — тогда программа просто
# обходится без них, а не падает.
ICON_NAME = "icon.ico"
LOGO_NAME = "logo.png"
STATE_NAME = "state.json"
# Отметка «проверка идёт»: кладётся в начале, убирается в конце. Осталась
# на месте — значит проверку оборвали, см. core/lastrun.py.
RUN_MARK_NAME = "run.json"
LOCK_NAME = "digest.lock"
# Замок самой программы — отдельный от замка проверки: они защищают
APP_LOCK_NAME = "app.lock"        # от разного и снимаются в разное время
DIGEST_DIRNAME = "digest"
# Данные поиска тем: список направлений, история отданных тем, кэш и выгрузки.
# Раньше всё это лежало рядом со скриптом — и терялось при каждой пересборке
# программы, потому что папку сборки PyInstaller сносит целиком.
TOPICS_DIRNAME = "topics"
# Мостик между агентами: короткие фразы, вытащенные проверкой из интересных
# постов. Их подхватывает сео-поиск как дополнительные запросы. Лежит в корне
# папки данных, а не внутри topics/: пишет его проверка, читает сео-поиск,
# и ничьей собственностью он не является.
FRESH_SEEDS_NAME = "fresh_seeds.json"
LOGS_DIRNAME = "logs"


def home():
    """Корень пользовательских данных. Абсолютный путь."""
    env = (os.environ.get("DIGEST_HOME") or "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if os.path.exists(os.path.join(app_dir(), SETTINGS_NAME)):
        return os.path.abspath(app_dir())                    # портативный режим
    return os.path.abspath(user_data_dir(APP_NAME, appauthor=False))


def frozen():
    """Запущены ли мы из собранного .exe, а не из исходников."""
    return bool(getattr(sys, "frozen", False))


def app_dir():
    """Папка, где лежит сама программа. Именно рядом с ней ищется settings.json
    в портативном режиме.

    В сборке это папка с .exe, а НЕ папка с кодом: код там спрятан внутри
    служебной подпапки, и складывать туда файлы человека нельзя — при
    обновлении программы они пропадут.
    """
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return config.PROJECT_ROOT


def code_dir():
    """Папка с файлами, приехавшими вместе с программой (заготовки настроек).

    Это НЕ папка пользователя: там лежит то, что человек правит, а здесь —
    то, что мы кладём в дистрибутив. В собранном .exe PyInstaller распаковывает
    такие файлы во временную папку и кладёт её путь в sys._MEIPASS.
    """
    return getattr(sys, "_MEIPASS", config.PROJECT_ROOT)


def settings_template():
    return os.path.join(code_dir(), SETTINGS_TEMPLATE_NAME)


def interests_template():
    return os.path.join(code_dir(), INTERESTS_TEMPLATE_NAME)


def icon_file():
    return os.path.join(code_dir(), ICON_NAME)


def logo_file():
    return os.path.join(code_dir(), LOGO_NAME)


def mode():
    """Каким из трёх правил выбран корень данных: "env", "portable" или "user".

    Нужно окну: человеку важно понимать, лежат его файлы рядом с программой
    или в папке пользователя. Правила те же и в том же порядке, что в home().
    """
    if (os.environ.get("DIGEST_HOME") or "").strip():
        return "env"
    if os.path.exists(os.path.join(app_dir(), SETTINGS_NAME)):
        return "portable"
    return "user"


def digest_dir():
    """Рабочая папка дайджеста: состояние, файл сессии, лок."""
    return os.path.join(home(), DIGEST_DIRNAME)


def topics_dir():
    """Рабочая папка поиска тем: направления, история, кэш, выгрузки."""
    return os.path.join(home(), TOPICS_DIRNAME)


def fresh_seeds_file():
    """Найденное проверкой в каналах — то, что подхватит сео-поиск."""
    return os.path.join(home(), FRESH_SEEDS_NAME)


def settings_file():
    return os.path.join(home(), SETTINGS_NAME)


def interests_file():
    return os.path.join(home(), INTERESTS_NAME)


def state_file():
    return os.path.join(digest_dir(), STATE_NAME)


def session_path(name="tg_digest"):
    """Путь к файлу сессии Telethon БЕЗ расширения: Telethon сам допишет
    .session. Имя приходит из настроек (telegram.session_name), поэтому оно
    параметр, а не константа: иначе paths пришлось бы импортировать settings,
    а settings уже импортирует paths."""
    return os.path.join(digest_dir(), str(name))


def lock_file():
    return os.path.join(digest_dir(), LOCK_NAME)


def run_mark_file():
    return os.path.join(digest_dir(), RUN_MARK_NAME)


def app_lock_file():
    return os.path.join(digest_dir(), APP_LOCK_NAME)


def logs_dir():
    return os.path.join(home(), LOGS_DIRNAME)


def ensure_dirs():
    """Создать недостающие папки. Вызывать перед первой записью на диск."""
    for path in (home(), digest_dir(), logs_dir()):
        os.makedirs(path, exist_ok=True)
