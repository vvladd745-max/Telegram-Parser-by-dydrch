import os

import requests
import time
from . import config, settings
from .logs import logger

TG_LIMIT = 4096      # жёсткий лимит Telegram на длину текстового сообщения


def credentials():
    """Токен бота и адресат отчётов. Возвращает (токен, chat_id).

    Порядок такой: сначала переменные окружения TG_BOT_TOKEN и TG_CHAT_ID —
    ими удобно подменять на время, потом настройки, потом config. В config
    теперь пусто: держать там чей-то настоящий токен нельзя, он уехал бы
    в дистрибутив вместе с кодом.
    """
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat:
        try:
            token = token or str(settings.get_secret("bot.token") or "").strip()
            chat = chat or str(settings.get("bot.chat_id", "") or "").strip()
        except settings.SettingsError:
            pass          # настроек нет — останется то, что в config
    token = token or config.BOT_TOKEN
    try:
        chat_id = int(chat) if chat else config.CHAT_ID
    except ValueError:
        chat_id = config.CHAT_ID
    return token, chat_id


def _url(method, token):
    # склейка строкой, а не f-string с фигурными скобками — чтобы токен не мешал
    return "https://" + "api.telegram.org/bot" + token + "/" + method


def split_text(text, limit=TG_LIMIT):
    """Режет текст на куски <= limit, стараясь рвать по переводам строк."""
    parts, cur = [], ""
    for line in text.split("\n"):
        # одна строка сама по себе длиннее лимита — рубим её жёстко
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = line if not cur else cur + "\n" + line
        if len(candidate) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts or [""]


def send_message(text, chat_id=None):
    """Текстовое сообщение через Bot API (sendMessage). Длинное — несколькими частями.
    Возвращает True, только если ушли ВСЕ части."""
    token, default_chat = credentials()
    parts = split_text(text)
    ok_all = True
    for i, part in enumerate(parts):
        try:
            r = requests.post(_url("sendMessage", token),
                              json={"chat_id": chat_id or default_chat, "text": part},
                              timeout=30)
            if not r.ok:
                logger.warning(f"   [!] sendMessage HTTP {r.status_code} {r.text}")
                ok_all = False
        except Exception as e:
            logger.warning(f"   [!] ошибка отправки сообщения: {e}")
            ok_all = False
        if i < len(parts) - 1:
            time.sleep(0.5)   # не влетаем в лимит частоты Bot API
    return ok_all


def send_document(path, caption="", chat_id=None):
    """Файл через Bot API (sendDocument). Возвращает True при успехе."""
    token, default_chat = credentials()
    try:
        with open(path, "rb") as f:
            r = requests.post(_url("sendDocument", token),
                              data={"chat_id": chat_id or default_chat,
                                    "caption": caption[:1024]},
                              files={"document": f}, timeout=60)
        if not r.ok:
            logger.warning(f"   [!] sendDocument HTTP {r.status_code} {r.text}")
        return r.ok
    except Exception as e:
        logger.warning(f"   [!] ошибка отправки файла: {e}")
        return False