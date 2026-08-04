"""Направления сео-поиска: единственное место, знающее файл spheres.json.

Файл читают и пишут двое: сам сео-поиск (topic_finder) и окно со списком
направлений. Формат один, и знать о нём должен один модуль — иначе однажды
они разойдутся, и на это уйдёт вечер.

Что внутри файла:

    {"cursor": 7,
     "blocks": [{"id": "windows",
                 "name": "Windows",
                 "seeds": ["windows 11", "настройка windows 11"]}]}

  id     — постоянное имя направления. Менять НЕЛЬЗЯ: по нему сео-поиск
           узнаёт свои кэш и квоты. Новым направлениям выдаётся свой.
  name   — то, что человек видит в окне.
  seeds  — запросы, с которых начинается сбор по направлению.
  cursor — где остановилась ротация: за прогон берётся несколько направлений
           по кругу. Берётся по остатку от их числа, поэтому устареть
           не может — но пустой список направлений уронил бы деление.
"""
import json
import os
import re

from . import paths

SPHERES_NAME = "spheres.json"


def path():
    return os.path.join(paths.topics_dir(), SPHERES_NAME)


def load():
    """Направления с диска. None — если файла ещё нет."""
    p = path()
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save(data):
    """Запись атомарная: сначала во временный файл рядом, потом замена.
    Сбой посреди записи не оставит обрезанный список направлений."""
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def new_id(blocks, name=""):
    """Постоянное имя для нового направления, не совпадающее с уже занятыми.

    Пробуем сделать его читаемым из названия (латиница и цифры), а если из
    названия ничего не осталось — берём порядковый номер. Читаемый id удобен,
    когда потом смотришь в файл руками.
    """
    taken = {str(b.get("id", "")) for b in blocks}
    base = re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower()).strip("_")
    if not base:
        base = "block"
    candidate = base
    n = 1
    while candidate in taken or not candidate:
        n += 1
        candidate = f"{base}_{n}"
    return candidate
