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


# Куда посылать человека за исправлением. Названия — ровно те, что он видит
# в окне. Раньше здесь стояло «раздел telegram, поле target»: это имена строк
# в файле настроек, которого он не открывает никогда, и подсказка получалась
# ни о чём. Меняются эти строки вместе с подписями в окне настроек.
WHERE_TELEGRAM = "«Настройки» → «Доступ к Telegram»"
WHERE_DEPTH = "«Настройки» → «Длительность проверки»"
WHERE_MODEL = "«Настройки» → «ИИ-модель для анализа постов»"
WHERE_BOT = "«Настройки» → «Отчёты»"

# Поля, которых в окне нет вовсе: они появляются в файле, только если его
# правили руками. Посылать за ними в окно бессмысленно.
WHERE_HAND = ("Такого поля в окне нет — значит, файл настроек правили вручную. "
              "Впишите положительное число или удалите строку целиком: "
              "тогда вернётся значение по умолчанию.")


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


def save_partial(values):
    """Записать только перечисленные поля, остальные настройки не трогая.

    values — словарь вида {"telegram": {"api_id": 123}}: разделы и поля
    накладываются поверх файла, всё прочее остаётся как было.

    Секреты уводятся в Диспетчер учётных данных, а в файле на их месте
    остаётся пусто. Если хранилище недоступно, значение остаётся в файле:
    потерять введённое хуже, чем сохранить его открытым текстом.

    Нужно окнам, которые правят кусочек настроек, — например странице входа
    в Telegram, где человек вводит api_id и api_hash, но больше ничего.
    """
    data = load(force=True)
    for section, fields in (values or {}).items():
        data.setdefault(section, {}).update(fields)
    for path in SECRET_PATHS:
        section, key = path.split(".", 1)
        if section not in (values or {}) or key not in (values.get(section) or {}):
            continue                       # это поле сейчас не правили
        secret = data.get(section, {}).get(key, "")
        if secret and set_secret(path, secret):
            data[section][key] = ""
    save(data)
    return data


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
    # Каждая строка сама говорит, куда идти: разделы разные, и общее
    # «загляните в Настройки» отправляло бы не туда в половине случаев.
    if api_id <= 0 or not get_secret("telegram.api_hash").strip():
        out.append("не заполнены api_id и api_hash — их выдают на my.telegram.org, "
                   "а вписывают в разделе «Настройки»")
    if not str(get("telegram.target", "") or "").strip():
        out.append("не указано, куда пересылать посты — это поле в разделе «Настройки»")
    if not channels():
        out.append("список каналов пуст — добавьте их в разделе «Каналы»")
    try:
        interests()
    except SettingsError:
        out.append("нет текста интересов, по нему модель отбирает посты — "
                   "напишите его в разделе «Интересы»")
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
        out.append("Не заполнен api_id — без него Telegram не пустит программу читать "
                   f"каналы. Поправить: {WHERE_TELEGRAM}. Там же ссылка, где его выдают.")
    if not get_secret("telegram.api_hash").strip():
        out.append("Не заполнен api_hash — он идёт в паре с api_id, и без него "
                   f"Telegram тоже не пустит. Поправить: {WHERE_TELEGRAM}.")
    if not str(tg.get("session_name") or "").strip():
        out.append("Стёрто имя файла, в котором хранится вход в Telegram. "
                   "Такого поля в окне нет — значит, файл настроек правили вручную. "
                   "Впишите обратно tg_digest или удалите строку session_name целиком.")
    if not str(tg.get("target") or "").strip():
        out.append("Не указано, куда пересылать отобранные посты. "
                   f"Поправить: {WHERE_TELEGRAM} → «Куда слать посты». Проще всего "
                   "завести канал для доставки на странице «Вход в Telegram» — "
                   "программа создаст его сама и подставит сюда.")

    links = channels()
    if not links:
        out.append("Список каналов пуст — читать нечего. "
                   "Добавьте каналы в разделе «Каналы».")
    bad = [c for c in links if not _links.looks_like_channel(c)]
    if bad:
        out.append(
            "Не похоже на адрес канала (" + str(len(bad)) + "): "
            + ", ".join(bad[:5]) + ("..." if len(bad) > 5 else "")
            + ". Проверьте их в разделе «Каналы»: адрес выглядит как @имя_канала "
              "или https://t.me/имя_канала."
        )

    # У каждого числа своё место в окне. Три последних поля в окне не показаны:
    # они нужны редко, и человек их не трогает.
    numbers = (
        ("lookback_hours", "за сколько часов смотреть посты при первой проверке канала",
         f"Поправить: {WHERE_DEPTH} → «Первая проверка канала»."),
        ("dry_run_hours", "за сколько часов смотреть посты в тестовой проверке",
         f"Поправить: {WHERE_DEPTH} → «Тестовая проверка»."),
        ("per_channel_limit", "сколько сообщений читать в канале за один раз", WHERE_HAND),
        ("flood_wait_cap", "сколько ждать, когда Telegram просит сделать паузу", WHERE_HAND),
        ("sent_keep", "сколько отправленных постов помнить по каждому каналу", WHERE_HAND),
    )
    for field, human, fix in numbers:
        try:
            val = int(dg.get(field))
        except (TypeError, ValueError):
            val = 0
        if val <= 0:
            out.append(f"Значение «{human}» должно быть положительным числом. {fix}")

    if not str(md.get("url") or "").strip():
        out.append("Не указан адрес модели — программе некуда обращаться за отбором "
                   f"постов. Поправить: {WHERE_MODEL} → «Адрес». Для LM Studio на этом "
                   "компьютере это http://localhost:1234/v1/chat/completions.")
    if not str(md.get("name") or "").strip():
        out.append("Не указано имя модели — непонятно, какую из них спрашивать. "
                   f"Поправить: {WHERE_MODEL} → «Имя модели».")

    if bot.get("enabled"):
        if not get_secret("bot.token").strip():
            out.append("Включены отчёты ботом, но не указан токен бота — отправлять "
                       f"их некому. Поправить: {WHERE_BOT} → «Токен бота»; там же ссылка "
                       "на @BotFather, который его выдаёт. Или снимите галочку "
                       "«Присылать отчёт о проверке ботом».")
        try:
            chat_id = int(bot.get("chat_id") or 0)
        except (TypeError, ValueError):
            chat_id = 0
        if chat_id == 0:
            out.append("Включены отчёты ботом, но не указано, кому их присылать. "
                       f"Поправить: {WHERE_BOT} → chat_id; это ваш числовой адрес "
                       "в Telegram, узнать его поможет ссылка в том же разделе. "
                       "Или снимите галочку «Присылать отчёт о проверке ботом».")

    if not os.path.exists(paths.interests_file()):
        out.append("Потерялся файл с описанием интересов — по нему модель решает "
                   "судьбу каждого поста. Откройте раздел «Интересы» и сохраните "
                   f"текст, файл создастся заново. Ищется он здесь: "
                   f"{paths.interests_file()}")

    try:
        version = int(data.get("schema_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version > SCHEMA_VERSION:
        out.append(
            f"Файл настроек остался от более новой версии программы (его версия "
            f"{version}, эта программа понимает {SCHEMA_VERSION}). Часть настроек "
            "может не примениться — стоит обновить программу."
        )

    return out
