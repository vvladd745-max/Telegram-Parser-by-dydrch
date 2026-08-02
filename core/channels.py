"""Разбор ссылок на Telegram-каналы. Без Telethon и без сети.

Модуль отвечает на четыре вопроса о строке из списка каналов:
кто это (ник), тот же ли это канал, как выглядит ссылка в едином виде
и похоже ли вообще на канал.

ВАЖНО: link_nick — это ключ памяти по id каналов в state.json (раздел __ids__).
Регулярка и порядок обрезки перенесены из digest/digest.py символ в символ.
Любая правка здесь ломает соответствие со старым состоянием: канал станет
«новым» и выдаст лавину дублей.
"""
import re

# схема, www, домен t.me или telegram.me, необязательный префикс превью /s/,
# дальше ник до первого слэша, знака вопроса или решётки
_LINK_NICK_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?([^/?#]+)", re.I)

# допустимый ник в Telegram: латиница, цифры, подчёркивание, 4-32 символа
_NICK_OK_RE = re.compile(r"^[a-z0-9_]{4,32}$")


def _link_tail(ch):
    """Хвост ссылки без схемы, домена, «собаки» и завершающего слэша.
    Регистр НЕ трогаем: у ссылок-приглашений хэш регистрозависимый."""
    s = str(ch).strip()
    m = _LINK_NICK_RE.match(s)
    tail = m.group(1) if m else s
    return tail.strip().lstrip("@").rstrip("/")


def link_nick(ch):
    """Ник канала из строки списка: схема, домен, слэши и хвосты отброшены.
    'https://t.me/X/', 'telegram.me/x', 't.me/x?single' и '@x' дают одно 'x'.
    Это и есть ключ памяти: он переживает косметическую правку ссылки."""
    return _link_tail(ch).lower()


def same_channel(a, b):
    """Две строки указывают на один и тот же канал.
    t.me/x, @X и https://t.me/x/ — это один канал, а не три."""
    return link_nick(a) == link_nick(b)


def is_invite_link(ch):
    """Ссылка-приглашение: t.me/+хэш или t.me/joinchat/хэш.
    В такой ссылке нет ника — проверять её на «похоже на ник» бессмысленно."""
    s = str(ch).strip()
    tail = _link_tail(s)
    if tail.startswith("+"):
        return True
    return tail.lower() == "joinchat" or "joinchat/" in s.lower()


def canonical_url(ch):
    """Ссылка в едином виде https://t.me/ник.

    Для приглашения возвращаем хвост как есть (регистр хэша значащий),
    для обычного канала — ник строчными буквами."""
    s = str(ch).strip()
    if is_invite_link(s):
        # у приглашения хвост может содержать слэш (joinchat/ХЭШ) — берём его целиком
        m = re.match(r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(.+)$", s, re.I)
        tail = (m.group(1) if m else s.lstrip("@")).strip().rstrip("/")
        return "https://t.me/" + tail
    return "https://t.me/" + link_nick(s)


def looks_like_channel(ch):
    """Правдоподобна ли строка как адрес канала.

    Это проверка формы, а не существования: канал может не открыться и с
    идеальным ником. Приглашения считаем допустимыми — их формат другой."""
    if is_invite_link(ch):
        return True
    return bool(_NICK_OK_RE.match(link_nick(ch)))
