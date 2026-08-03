"""Чтение настроек из файлов, а не из кода.

Где лежат файлы, решает core.paths — здесь мы только читаем то, что он показал:
  paths.settings_file()   — все параметры;
  paths.interests_file()  — текст промпта-фильтра.

Отсутствующий в файле ключ не должен ронять программу: прочитанное
накладывается на DEFAULTS рекурсивным слиянием, недостающее берётся оттуда.
"""
import json
import os
import shutil

from .logs import logger
from . import paths
from . import secrets as _store
from . import channels as _links


SCHEMA_VERSION = 1

# Что считается секретом и потому живёт в Диспетчере учётных данных, а не
# в settings.json. Ключ здесь — тот же точечный путь, что и в файле.
SECRET_PATHS = ("telegram.api_hash", "bot.token", "model.api_key")

# Полный список ключей со значениями «по умолчанию». Это же и документация:
# чего в settings.json нет — берётся отсюда.
DEFAULTS = {
    "schema_version": SCHEMA_VERSION,
    "telegram": {
        "api_id": 0,             # api_id с my.telegram.org (число)
        "api_hash": "",          # api_hash оттуда же (строка)
        "session_name": "tg_digest",   # имя файла сессии Telethon
        "target": "",            # куда пересылать отобранное
    },
    "digest": {
        "lookback_hours": 28,    # окно первого запуска по каналу
        "dry_run_hours": 2,      # окно по умолчанию для --dry-run
        "per_channel_limit": 200,  # сколько сообщений читать за раз
        "flood_wait_cap": 600,   # дольше ждать FloodWait не будем
        "sent_keep": 400,        # сколько id отправленных постов помним на канал
        "extract_seeds": True,   # копить поисковые затравки для topic_finder
    },
    "model": {
        "url": "http://localhost:1234/v1/chat/completions",
        "name": "qwen3-8b-128k",
        "api_key": "",           # LM Studio ключ не требует; поле на будущее
    },
    "bot": {
        "enabled": False,        # слать ли итоговый отчёт ботом.
                                 # По умолчанию выключено: бота ещё надо завести,
                                 # а без него отчёт всё равно некуда слать.
        "token": "",
        "chat_id": 0,
    },
    "ui": {
        "matrix": True,          # печатать журнал проверки посимвольно
        "theme": "system",       # тема окна: system, light или dark
        "font_size": 0,          # размер букв в пунктах; 0 — как в системе
    },
    "schedule": {
        # Память окна о расписании. Сама задача живёт в Планировщике заданий
        # Windows, см. core/schedule.py; здесь только то, что показать человеку.
        "enabled": False,        # выключено, пока человек не включит сам
        "time": "08:00",         # во сколько запускать, «ЧЧ:ММ»
        "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    },
    "channels": [],              # список ссылок на каналы
}


class SettingsError(Exception):
    """Настройки не прочитать: файла нет, он испорчен или это не объект JSON.

    Текст исключения написан для человека и годится, чтобы показать его как есть.
    """


_cache = None
_cache_path = None


def _merge(base, over):
    """Рекурсивное слияние: значения из over поверх base, вложенные словари
    сливаются, а не заменяются целиком."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def reset_cache():
    """Забыть прочитанное — следующий load() пойдёт на диск."""
    global _cache, _cache_path
    _cache = None
    _cache_path = None


def bootstrap():
    """Первый запуск: раскладывает заготовки настроек в папку пользователя.

    Копируются только недостающие файлы — то, что человек уже правил,
    не трогается никогда. Заготовки лежат рядом с программой и личных данных
    не содержат: ни api_id, ни api_hash, ни токена бота. Список каналов и текст
    интересов в них есть — с ними можно начинать работу сразу.

    Возвращает список созданных файлов (пустой, если всё уже было на месте).
    """
    created = []
    pairs = ((paths.settings_template(), paths.settings_file()),
             (paths.interests_template(), paths.interests_file()))
    for src, dst in pairs:
        # в портативном режиме заготовка и рабочий файл — это один и тот же
        # путь; копировать файл сам в себя нельзя
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        if os.path.exists(dst) or not os.path.exists(src):
            continue
        paths.ensure_dirs()
        shutil.copyfile(src, dst)
        created.append(dst)
    if created:
        reset_cache()
    return created


def load(force=False):
    """Настройки целиком (DEFAULTS плюс то, что в файле). Результат кэшируется.

    Кэш привязан к пути: смена DIGEST_HOME сама заставит перечитать файл.
    """
    global _cache, _cache_path
    path = paths.settings_file()
    if not force and _cache is not None and _cache_path == path:
        return _cache

    if not os.path.exists(path):
        raise SettingsError(
            f"Не найден файл настроек: {path}. "
            "Создайте его или укажите папку с настройками в переменной DIGEST_HOME."
        )
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise SettingsError(
            f"Файл настроек испорчен: {path}, строка {e.lineno} — {e.msg}. "
            "Чаще всего это лишняя или пропущенная запятая либо кавычка."
        ) from None
    except OSError as e:
        raise SettingsError(f"Не удалось прочитать файл настроек: {path} ({e}).") from None

    if not isinstance(raw, dict):
        raise SettingsError(
            f"Файл настроек {path} должен начинаться с фигурной скобки и содержать "
            "набор параметров, а не список или одно значение."
        )

    _cache = _merge(DEFAULTS, raw)
    _cache_path = path
    return _cache


def save(data):
    """Записать настройки атомарно: сначала во временный файл рядом, потом
    os.replace. Сбой посреди записи не оставит обрезанный settings.json.
    Кэш обновляется тем же слиянием, что и при чтении."""
    global _cache, _cache_path
    path = paths.settings_file()
    tmp = path + ".tmp"
    paths.ensure_dirs()
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _cache = _merge(DEFAULTS, data)
    _cache_path = path


def get(path, default=None):
    """Значение по точечному пути: get("telegram.api_id").
    Если ключа нет ни в файле, ни в DEFAULTS — вернётся default."""
    node = load()
    for part in str(path).split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def get_secret(path, default=""):
    """Секрет: сначала Диспетчер учётных данных, потом settings.json.

    Запасной путь через файл нужен не для красоты: так продолжают работать
    настройки, которые ещё не переехали в хранилище, и машины, где хранилища
    нет вовсе.
    """
    value = _store.get(path)
    if value:
        return value
    return str(get(path, default) or "")


def set_secret(path, value):
    """Положить секрет в хранилище. True — получилось, и из файла его
    можно убирать; False — хранилища нет, придётся хранить в файле."""
    return _store.store(path, value)


def migrate_secrets():
    """Перенести секреты из settings.json в Диспетчер учётных данных.

    Файл правится ТОЛЬКО после успешной записи в хранилище: иначе секрет
    пропал бы совсем. Возвращает список перенесённых путей.
    """
    if not _store.available():
        return []
    try:
        data = load(force=True)
    except SettingsError:
        return []

    moved = []
    for path in SECRET_PATHS:
        value = str(get(path, "") or "").strip()
        if not value:
            continue
        if not _store.store(path, value):
            continue
        section, key = path.split(".", 1)
        data.setdefault(section, {})[key] = ""
        moved.append(path)
    if moved:
        save(data)
        logger.info("Секреты перенесены в Диспетчер учётных данных Windows: "
                    + ", ".join(moved))
    return moved


def channels(enabled_only=True):
    """Список ссылок на каналы в порядке из файла, без дублей.

    Дубли отбрасываются ПО НИКУ (core.channels.link_nick), а не по строке:
    't.me/x' и '@x' — один канал, а не два. Выигрывает первое вхождение.

    Элемент списка — либо строка-ссылка, либо словарь вида
    {"url": "...", "enabled": true}: так список переживёт появление
    галочек в будущем окне настроек.
    """
    out = []
    seen = set()
    for item in load().get("channels") or []:
        if isinstance(item, dict):
            if enabled_only and not item.get("enabled", True):
                continue
            link = item.get("url") or item.get("link") or ""
        else:
            link = item
        link = str(link).strip()
        if not link:
            continue
        nick = _links.link_nick(link)
        if nick in seen:
            continue
        seen.add(nick)
        out.append(link)
    return out


def interests():
    """Текст промпта-фильтра из interests.txt, как есть, без правок.

    Не обрезаем и не нормализуем: текст выверен прогонами, любое изменение
    меняет качество фильтра.
    """
    path = paths.interests_file()
    if not os.path.exists(path):
        raise SettingsError(
            f"Не найден файл с описанием интересов: {path}. "
            "Без него фильтр постов работать не может."
        )
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:
        raise SettingsError(f"Не удалось прочитать файл интересов: {path} ({e}).") from None
    if not text.strip():
        raise SettingsError(f"Файл интересов пуст: {path}. Опишите, какие посты вам нужны.")
    return text


def save_interests(text):
    """Записать текст интересов атомарно, как и настройки.

    Текст пишется ровно так, как пришёл: ни обрезки, ни нормализации.
    Он выверен прогонами, и «причёсывание» здесь меняет качество фильтра.
    """
    path = paths.interests_file()
    paths.ensure_dirs()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def blockers():
    """Чего не хватает, чтобы вообще начать проверку. Пустой список — можно.

    Отличается от problems(): там все замечания, включая необязательные,
    а здесь только то, без чего проверка гарантированно упадёт.
    """
    out = []
    try:
        load()
    except SettingsError as e:
        return [str(e)]

    try:
        api_id = int(get("telegram.api_id") or 0)
    except (TypeError, ValueError):
        api_id = 0
    if api_id <= 0 or not get_secret("telegram.api_hash").strip():
        out.append("не заполнены api_id и api_hash — их выдают на my.telegram.org")
    if not str(get("telegram.target", "") or "").strip():
        out.append("не указано, куда пересылать посты")
    if not channels():
        out.append("список каналов пуст")
    try:
        interests()
    except SettingsError:
        out.append("нет текста интересов — по нему модель отбирает посты")
    return out


def problems():
    """Понятные человеку претензии к настройкам. Пустой список — всё в порядке.

    Это не исключение и не запрет запуска: список показывается в окне,
    решение принимает человек.
    """
    try:
        data = load()
    except SettingsError as e:
        return [str(e)]

    out = []
    tg = data.get("telegram", {})
    dg = data.get("digest", {})
    md = data.get("model", {})
    bot = data.get("bot", {})

    try:
        api_id = int(tg.get("api_id") or 0)
    except (TypeError, ValueError):
        api_id = 0
    if api_id <= 0:
        out.append("Не указан api_id из my.telegram.org (раздел telegram, поле api_id).")
    if not get_secret("telegram.api_hash").strip():
        out.append("Не указан api_hash из my.telegram.org (раздел telegram, поле api_hash).")
    if not str(tg.get("session_name") or "").strip():
        out.append("Не указано имя файла сессии Telegram (раздел telegram, поле session_name).")
    if not str(tg.get("target") or "").strip():
        out.append("Не указано, куда пересылать посты (раздел telegram, поле target).")

    links = channels()
    if not links:
        out.append("Список каналов пуст — читать нечего (раздел channels).")
    bad = [c for c in links if not _links.looks_like_channel(c)]
    if bad:
        out.append(
            "Не похожи на адрес канала (" + str(len(bad)) + "): "
            + ", ".join(bad[:5]) + ("..." if len(bad) > 5 else "")
        )

    for field, human in (("lookback_hours", "окно первого запуска"),
                         ("dry_run_hours", "окно тестового прогона"),
                         ("per_channel_limit", "сколько сообщений читать на канал"),
                         ("flood_wait_cap", "предел ожидания при FloodWait"),
                         ("sent_keep", "сколько id отправленных постов помнить")):
        try:
            val = int(dg.get(field))
        except (TypeError, ValueError):
            val = 0
        if val <= 0:
            out.append(f"Параметр digest.{field} ({human}) должен быть положительным числом.")

    if not str(md.get("url") or "").strip():
        out.append("Не указан адрес локальной модели (раздел model, поле url).")
    if not str(md.get("name") or "").strip():
        out.append("Не указано имя модели (раздел model, поле name).")

    if bot.get("enabled"):
        if not get_secret("bot.token").strip():
            out.append("Отчёты ботом включены, но не указан токен бота (раздел bot, поле token).")
        try:
            chat_id = int(bot.get("chat_id") or 0)
        except (TypeError, ValueError):
            chat_id = 0
        if chat_id == 0:
            out.append("Отчёты ботом включены, но не указан chat_id получателя (раздел bot).")

    if not os.path.exists(paths.interests_file()):
        out.append(f"Не найден файл с описанием интересов: {paths.interests_file()}.")

    try:
        version = int(data.get("schema_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version > SCHEMA_VERSION:
        out.append(
            f"Файл настроек версии {version}, а программа понимает версию {SCHEMA_VERSION} — "
            "похоже, настройки от более новой версии программы."
        )

    return out
