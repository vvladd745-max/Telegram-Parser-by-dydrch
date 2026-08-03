"""Отметка о том, что проверка началась и не закончилась.

Зачем это нужно. Замок прогона снимает сама Windows, как только процесс умер,
и по нему потом не отличить «программа отработала» от «компьютер выключили
посреди работы». Программа просыпается с чистой памятью и молчит, хотя
сказать есть о чём.

Что после обрыва в порядке, а что нет:
  * закладки по каналам целы — они двигаются по ходу дела и остаются на
    последнем успешно отправленном посте. Посты не теряются, недочитанное
    придёт в следующий раз. Чинить тут нечего;
  * модель остаётся висеть в памяти LM Studio — несколько гигабайт до
    перезагрузки компьютера, потому что уборка не отработала;
  * человек не знает, что проверка не доделана.

Поэтому в начале проверки кладётся файл-отметка, а в конце убирается. Лежит
на месте при следующем запуске — значит проверку оборвали. В отметке записано
и то, что мы подняли в LM Studio: по ней уборка доделывается задним числом.

Отметка — вещь служебная и необязательная. Любая ошибка при работе с ней
уходит в журнал и не мешает ни проверке, ни запуску программы: потерянная
отметка стоит строчки в журнале, а сорванная из-за неё проверка — рабочего дня.
"""
import json
import os
from datetime import datetime

from . import paths
from .logs import logger


def _write(data):
    try:
        paths.ensure_dirs()
        path = paths.run_mark_file()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"   [!] Не удалось записать отметку о проверке: {e}")


def read():
    """Отметка или None, если её нет либо она испорчена."""
    path = paths.run_mark_file()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"   [!] Отметка о проверке испорчена: {e}")
        return None
    return data if isinstance(data, dict) else None


def started(dry_run):
    """Проверка началась. Зовётся до подъёма модели."""
    _write({"started": datetime.now().isoformat(timespec="seconds"),
            "dry_run": bool(dry_run),
            "lms": {}})


def remember_lms(done):
    """Запомнить, что мы подняли в LM Studio: по этому потом убираем.

    Отдельным вызовом, а не вместе со started: что именно поднято, известно
    только после подъёма, а отметка нужна раньше — на случай обрыва прямо
    во время загрузки модели.
    """
    data = read() or {"started": datetime.now().isoformat(timespec="seconds"),
                      "dry_run": False}
    data["lms"] = dict(done or {})
    _write(data)


def finished():
    """Проверка закончилась своим ходом — отметку убираем."""
    try:
        os.remove(paths.run_mark_file())
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"   [!] Не удалось убрать отметку о проверке: {e}")


def interrupted():
    """Что осталось от оборванной проверки, или None.

    Возвращает словарь: when — когда началась (datetime или None),
    dry_run — была ли она тестовой, lms — что мы подняли и не убрали.
    """
    data = read()
    if data is None:
        return None
    try:
        when = datetime.fromisoformat(str(data.get("started") or ""))
    except ValueError:
        when = None
    return {"when": when,
            "dry_run": bool(data.get("dry_run")),
            "lms": data.get("lms") or {}}


def when_text(when):
    """Когда это было — словами: «сегодня в 20:15», «вчера в 08:00»."""
    if when is None:
        return "в прошлый раз"
    today = datetime.now().date()
    shift = (today - when.date()).days
    clock = when.strftime("%H:%M")
    if shift == 0:
        return f"сегодня в {clock}"
    if shift == 1:
        return f"вчера в {clock}"
    return when.strftime("%d.%m.%Y в %H:%M")
