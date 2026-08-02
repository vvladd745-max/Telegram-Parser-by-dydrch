"""Общий «мостик» между агентами: свежие поисковые затравки.

digest вытаскивает из интересных постов короткие фразы и складывает сюда,
а topic_finder подхватывает их как дополнительные затравки для Bukvarix.
Файл лежит в корне проекта (core/config.FRESH_SEEDS_FILE) — виден обоим.
"""
import json, os, datetime
from . import config

def _load():
    path = config.FRESH_SEEDS_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("seeds"), list):
                return data["seeds"]
        except Exception:
            pass
    return []

def _save(seeds):
    # атомарная запись: temp-файл рядом + os.replace (прерывание не оставит битый JSON)
    tmp = config.FRESH_SEEDS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"seeds": seeds}, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, config.FRESH_SEEDS_FILE)

def _norm(p):
    return " ".join(p.lower().split())

def add_fresh_seeds(phrases, max_keep=200):
    """Добавляет фразы с сегодняшней датой. Дубли не плодит: у повтора
    обновляет дату и счётчик hits. Хранит не больше max_keep самых свежих."""
    seeds = _load()
    index = {_norm(s["phrase"]): s for s in seeds if s.get("phrase")}
    today = datetime.date.today().isoformat()
    for raw in phrases:
        p = (raw or "").strip()
        if len(p) < 3:
            continue
        key = _norm(p)
        if key in index:
            index[key]["ts"] = today
            index[key]["hits"] = index[key].get("hits", 1) + 1
        else:
            rec = {"phrase": p, "ts": today, "hits": 1}
            index[key] = rec
            seeds.append(rec)
    seeds.sort(key=lambda s: s.get("ts", ""))   # свежие — в конец
    seeds = seeds[-max_keep:]
    _save(seeds)
    return len(seeds)

def load_fresh_seeds(max_age_days=10, limit=12):
    """Возвращает фразы не старше max_age_days: сначала чаще встречавшиеся,
    потом более свежие. Пустой список — если мостик ещё не наполнен."""
    seeds = _load()
    if not seeds:
        return []
    cutoff = (datetime.date.today() - datetime.timedelta(days=max_age_days)).isoformat()
    fresh = [s for s in seeds if s.get("ts", "") >= cutoff]
    fresh.sort(key=lambda s: (s.get("hits", 1), s.get("ts", "")), reverse=True)
    return [s["phrase"] for s in fresh[:limit]]

def record_seed_health(dead_phrases, alive_phrases=(), max_fails=2):
    """Счётчик здоровья свежих затравок.

    У затравки, по которой Bukvarix что-то вернул, счётчик сбрасывается.
    У пустой — растёт; дорос до max_fails — запись удаляется из файла.
    Два провала, а не один — чтобы случайный сбой API не выкинул живую фразу.

    Вызывать ТОЛЬКО после живого прохода: в --dry-run пустой ответ значит
    лишь отсутствие кэша, а не мёртвую затравку.

    Возвращает список удалённых фраз."""
    seeds = _load()
    if not seeds:
        return []
    dead = {_norm(p) for p in dead_phrases if p}
    alive = {_norm(p) for p in alive_phrases if p}
    if not dead and not alive:
        return []
    kept, removed = [], []
    for s in seeds:
        key = _norm(s.get("phrase", ""))
        if key in alive:
            s["fails"] = 0
        elif key in dead:
            s["fails"] = s.get("fails", 0) + 1
            if s["fails"] >= max_fails:
                removed.append(s.get("phrase", ""))
                continue
        kept.append(s)
    _save(kept)
    return removed