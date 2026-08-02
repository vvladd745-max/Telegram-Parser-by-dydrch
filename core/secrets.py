"""Секреты в Диспетчере учётных данных Windows.

Зачем отдельный модуль. Диспетчер учётных данных общий на всю машину и
НЕ зависит от DIGEST_HOME. Значит песочница и проверки, если писать в него
как попало, затрут настоящие ключи человека. Поэтому имя хранилища берётся
из функции service(), и его можно подменить переменной окружения
DIGEST_KEYRING_SERVICE — этим пользуются песочница и тесты.

Хранилище может быть недоступно (нет keyring, чужая система, сборка без
нужного модуля). Это не повод падать: тогда все функции ведут себя как
«секрета нет», а вызывающий код берёт значение из settings.json, как раньше.
"""
import os

from .logs import logger

SERVICE_DEFAULT = "TelegramDigest"

try:
    import keyring as _keyring
except Exception as e:          # библиотеки нет — работаем без хранилища
    _keyring = None
    logger.warning(f"   [!] Хранилище секретов недоступно: {e}")


def service():
    """Имя, под которым секреты лежат в Диспетчере учётных данных."""
    return (os.environ.get("DIGEST_KEYRING_SERVICE") or "").strip() or SERVICE_DEFAULT


def available():
    """Можно ли вообще пользоваться хранилищем."""
    if _keyring is None:
        return False
    try:
        _keyring.get_password(service(), "__проверка__")
        return True
    except Exception as e:
        logger.warning(f"   [!] Хранилище секретов не отвечает: {e}")
        return False


def get(name):
    """Секрет из хранилища или "" — если его там нет или хранилище недоступно."""
    if _keyring is None:
        return ""
    try:
        return _keyring.get_password(service(), name) or ""
    except Exception as e:
        logger.warning(f"   [!] Не удалось прочитать секрет {name}: {e}")
        return ""


def store(name, value):
    """Положить секрет в хранилище. True — получилось.

    Пустое значение означает «убрать»: держать в Диспетчере пустышку незачем.
    """
    if _keyring is None:
        return False
    value = str(value or "")
    try:
        if value:
            _keyring.set_password(service(), name, value)
        else:
            delete(name)
        return True
    except Exception as e:
        logger.warning(f"   [!] Не удалось сохранить секрет {name}: {e}")
        return False


def delete(name):
    """Убрать секрет из хранилища. Отсутствие записи — не ошибка."""
    if _keyring is None:
        return False
    try:
        _keyring.delete_password(service(), name)
        return True
    except Exception:
        return False
