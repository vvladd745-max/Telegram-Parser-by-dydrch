"""ЕДИНСТВЕННОЕ место, которое знает про прокси.

Зачем это вообще нужно. В Telegram программа ходит двумя разными дорогами,
и они устроены по-разному. Отчёт боту едет обычным HTTPS через requests —
та сама заглядывает в настройки Windows и в подсказках не нуждается.
А посты читает Telethon по протоколу MTProto: это не HTTPS, и в системные
настройки Windows Telethon не смотрит НИКОГДА, ни на какой платформе.
Прокси ему надо передать в руки, параметром при создании клиента.
Отсюда этот модуль: он и есть тот самый параметр.

Адрес берётся у самой Windows — тот же прокси, что человек вписал
в «Параметры» → «Сеть и Интернет» → «Прокси-сервер» и через который у него
уже работает обычный Telegram. Своего поля в настройках программы нет
намеренно: настраивать прокси в двух местах и следить, чтобы они совпадали,
человеку незачем.

Выключается там же, где включается. Убрали прокси в Windows — программа
пойдёт к Telegram напрямую, ровно как ходила раньше. Отдельной галочки
«не использовать прокси» в программе нет.

Разбираться в протоколах от человека не требуется: что Windows написала,
то и берём. HTTP-прокси для MTProto годится — соединение внутри туннеля
всё равно сырое, TCP.
"""
import urllib.parse
import urllib.request

from .logs import logger

# Про какой прокси мы уже сказали в журнал. Клиент Telethon создаётся не один
# раз за сеанс (вход, проверка ссылок, сам прогон), и без этой отметки одна
# и та же строка повторялась бы человеку по десять раз.
_told = None

# Что Windows называет прокси и во что это превращается для Telethon.
# Ключ — схема из адреса, значение — как называет протокол python_socks.
_SCHEMES = {
    "http": "http",
    "https": "http",        # HTTP CONNECT, схема https тут ничего не меняет
    "socks5": "socks5",
    "socks5h": "socks5",    # h — «имена разрешает прокси»; для нас то же самое
    "socks4": "socks4",
    "socks4a": "socks4",
}


def _pick():
    """Строка адреса прокси из настроек Windows или пустая строка.

    getproxies() сначала смотрит переменные окружения (*_proxy), потом реестр
    Windows — то есть ровно то, что показывает окно «Прокси-сервер».

    Порядок перебора не случаен: явно указанный socks идёт первым. Он для
    MTProto подходит лучше всего, и если человек его прописал, то именно его
    и имел в виду.
    """
    try:
        found = urllib.request.getproxies()
    except Exception as e:                       # мало ли что в реестре
        logger.warning(f"   [!] настройки прокси Windows не прочитались: {e}")
        return ""
    for key in ("socks", "https", "http"):
        value = str(found.get(key) or "").strip()
        if value:
            return value
    return ""


def _parse(value):
    """Адрес прокси -> (протокол, узел, порт, логин, пароль) или None.

    Адрес приходит в разном виде: с протоколом (http://узел:порт) и без него
    (просто узел:порт — так пишут в реестре). Без протокола считаем, что это
    HTTP: именно он стоит в окне Windows «Прокси-сервер».
    """
    if "//" not in value:
        value = "http://" + value
    try:
        u = urllib.parse.urlparse(value)
        host, port = u.hostname, u.port
    except ValueError:                           # кривой порт, битая строка
        host, port = None, None
    if not host or not port:
        logger.warning(f"   [!] адрес прокси не разобрать: {value}. Иду напрямую.")
        return None
    kind = _SCHEMES.get((u.scheme or "http").lower())
    if kind is None:
        logger.warning(f"   [!] прокси вида «{u.scheme}» не умею. Иду напрямую.")
        return None
    return (kind, host, int(port), u.username or None, u.password or None)


def for_telethon():
    """То, что передаётся в TelegramClient(..., proxy=...).

    None означает «никакого прокси»: Telethon в этом случае соединяется
    напрямую, как и раньше. Это НЕ ошибка и не повод ругаться — у большинства
    людей прокси и не будет, у них Telegram открыт и так.
    """
    global _told
    value = _pick()
    if not value:
        return None
    parsed = _parse(value)
    if parsed is None:
        return None
    kind, host, port, user, password = parsed
    where = f"{host}:{port}"
    if _told != where:
        logger.info(f"Иду в Telegram через прокси {where} — тот же, что указан "
                    f"в настройках Windows.")
        _told = where
    # Порядок полей — как ждёт Telethon: тип, узел, порт, разрешать ли имена
    # на стороне прокси, логин, пароль.
    return (kind, host, port, True, user, password)
