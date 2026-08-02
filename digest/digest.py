import sys, os
# Корень проекта в путь — чтобы работал импорт пакета core/ из любой папки.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json, re, asyncio, datetime
import portalocker
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import PeerChannel
from core import llm, telegram, seeds, logs, settings, paths
from core.llm import LLMUnavailable
from core.channels import link_nick
from core.logs import logger

# ====== НАСТРОЙКИ digest ======
# Самих значений здесь больше нет: они в settings.json и interests.txt
# (папка из переменной DIGEST_HOME, по умолчанию — корень проекта).
# Этот файл их только читает.

def _read_settings():
    """Настройки и текст интересов. Если файла нет или он испорчен —
    одна понятная строка по-русски и код возврата 2, без трассировки."""
    try:
        settings.load()
        return settings.interests()
    except settings.SettingsError as e:
        logger.error(f"[!] {e}")
        sys.exit(2)


INTERESTS = _read_settings()        # текст фильтра из interests.txt, как есть

API_ID = settings.get("telegram.api_id")        # api_id с my.telegram.org (число)
API_HASH = settings.get_secret("telegram.api_hash")   # из Диспетчера учётных данных
# где лежит файл сессии Telethon, решает core/paths (в портативном режиме —
# всё та же digest/tg_digest.session рядом с кодом)
SESSION = paths.session_path(settings.get("telegram.session_name"))
TARGET = settings.get("telegram.target")   # @ник приватного канала доставки
# Каналы для мониторинга: ссылки из settings.json, дубли по нику уже отброшены
CHANNELS = settings.channels()

LOOKBACK_HOURS = settings.get("digest.lookback_hours")   # за сколько часов брать посты на первом запуске
DRY_RUN_HOURS = settings.get("digest.dry_run_hours")     # окно по умолчанию для --dry-run
FLOOD_WAIT_CAP = settings.get("digest.flood_wait_cap")   # дольше ждать FloodWait не будем — отложим канал
SENT_KEEP = settings.get("digest.sent_keep")             # сколько последних id на канал помним
# Сбор поисковых затравок для отдельного инструмента topic_finder.
# Посторонним он не нужен, поэтому в заготовке настроек выключен.
EXTRACT_SEEDS = bool(settings.get("digest.extract_seeds", False))

# состояние и lock-файл — тоже из core/paths, одним источником с сессией
STATE_FILE = paths.state_file()
LOCK_FILE = paths.lock_file()   # защита от двойного боевого запуска
SENT_KEY = "__sent__"          # реестр id уже пересланных постов (защита от повторной отправки)
IDS_KEY = "__ids__"            # память по каналам: ссылка из CHANNELS -> {id, ключ состояния}
# =============================================

def _arg_hours(dry_run):
    """Окно просмотра в часах. Флаг: --hours 6  или  --hours=6.
    По умолчанию: DRY_RUN_HOURS в тесте, LOOKBACK_HOURS в боевом прогоне."""
    for i, a in enumerate(sys.argv):
        if a == "--hours" and i + 1 < len(sys.argv):
            try:
                return max(1, int(sys.argv[i + 1]))
            except ValueError:
                pass
        if a.startswith("--hours="):
            try:
                return max(1, int(a.split("=", 1)[1]))
            except ValueError:
                pass
    return DRY_RUN_HOURS if dry_run else LOOKBACK_HOURS

def _chan_key(ch, entity):
    """Ключ состояния = username канала, а не URL из списка CHANNELS.
    URL — плохой ключ: смена домена или добавление слэша сбрасывает канал в ноль
    и он перечитывается с самого начала."""
    u = getattr(entity, "username", None)
    if u:
        return "@" + str(u).lower()
    return "id" + str(getattr(entity, "id", ch))

def _migrate_key(state, old_key, new_key):
    """Разовый перенос состояния со старого ключа-URL на новый ключ-username."""
    moved = False
    if new_key not in state and old_key in state:
        state[new_key] = state.pop(old_key)
        moved = True
    sent_map = state.setdefault(SENT_KEY, {})
    if new_key not in sent_map and old_key in sent_map:
        sent_map[new_key] = sent_map.pop(old_key)
        moved = True
    return moved

# ник канала из ссылки (ключ памяти по id) теперь живёт в core/channels.py —
# им пользуются и digest, и будущее окно настроек; логика та же, что была здесь

def _chan_memo(state, ch):
    """Что помним про канал: числовой id и ключ состояния. id канала в
    Telegram не меняется никогда — это наш якорь.

    Ищем в три захода:
      1) по нику из ссылки — основной ключ;
      2) по полной ссылке — старый формат волны 4, читаем для совместимости;
      3) по ключу состояния '@ник' среди всех записей — спасает, если ссылка
         в CHANNELS была переписана руками до неузнаваемости."""
    ids = state.setdefault(IDS_KEY, {})
    nick = link_nick(ch)
    for probe in (nick, str(ch)):
        memo = ids.get(probe)
        if isinstance(memo, dict) and memo.get("id"):
            return memo
    want = "@" + nick
    for memo in ids.values():
        if isinstance(memo, dict) and memo.get("key") == want and memo.get("id"):
            return memo
    return {}

def _remember_chan(state, ch, entity, key):
    """Запоминаем id канала и ключ состояния под ником, а не под полной
    ссылкой. Заодно выкидываем старую запись-URL из волны 4, чтобы
    в state.json не копились два формата разом."""
    cid = getattr(entity, "id", None)
    if cid is None:
        return
    ids = state.setdefault(IDS_KEY, {})
    nick = link_nick(ch)
    if str(ch) != nick:
        ids.pop(str(ch), None)
    ids[nick] = {"id": cid, "key": key}

async def _open_channel(client, ch, state):
    """Открываем канал: сначала по ссылке из CHANNELS, потом — по запомненному id.

    Возвращает (entity, note):
      - (канал, "")            — открылся по ссылке, всё штатно;
      - (канал, "новая ссылка") — ссылка протухла, но канал найден по id;
      - (None, "текст ошибки") — не открылся ничем.
    FloodWaitError пробрасываем наружу: его обрабатывает вызывающий код."""
    try:
        return await client.get_entity(ch), ""
    except FloodWaitError:
        raise
    except Exception as e:
        first_err = e
    cid = _chan_memo(state, ch).get("id")
    if not cid:
        return None, f"{first_err} (id канала не запомнен — страховать нечем)"
    try:
        entity = await client.get_entity(PeerChannel(cid))
    except Exception as e2:
        return None, f"{first_err}; по запомненному id тоже не открылся ({e2})"
    u = getattr(entity, "username", None)
    return entity, ("https://t.me/" + str(u)) if u else f"id{cid} (канал стал приватным)"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    # атомарная запись: сначала во временный файл рядом, потом os.replace
    # (прерывание/сбой не оставит битый state.json)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)

_lock_handle = None    # открытый файл лока; пока он жив — блокировка наша

def acquire_lock():
    """Не даём двум боевым прогонам идти разом (иначе задвоение постов и гонка
    за state.json). True — лок наш, False — прогон уже идёт.

    Блокировку держит операционная система, а не наличие файла на диске:
    если процесс убили или машина перезагрузилась, лок снимается сам. Поэтому
    проверка «файл старше трёх часов — считаем зависшим» больше не нужна."""
    global _lock_handle
    paths.ensure_dirs()
    fh = open(LOCK_FILE, "a+", encoding="utf-8")
    try:
        portalocker.lock(fh, portalocker.LOCK_EX | portalocker.LOCK_NB)
    except portalocker.exceptions.BaseLockException:
        fh.close()
        return False
    # пишем pid — не для логики, а чтобы по файлу было видно, кто держит лок
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    _lock_handle = fh
    return True

def release_lock():
    """Отпускаем блокировку. Сам файл не удаляем: он пустой якорь, а удаление
    открытого другими процессами файла на Windows — источник гонок."""
    global _lock_handle
    if _lock_handle is None:
        return
    try:
        portalocker.unlock(_lock_handle)
    finally:
        _lock_handle.close()
        _lock_handle = None

def clip_for_filter(text, limit=4000, tail=1200):
    # обычный пост Telegram (<= ~4096) отдаём целиком;
    # сверхдлинный — начало + конец, чтобы не потерять erid/#реклама в хвосте
    text = text.strip()
    if len(text) <= limit:
        return text
    head = limit - tail
    return text[:head] + "\n[…пропущена середина…]\n" + text[-tail:]

def is_interesting(text):
    prompt = (
        f"{INTERESTS}\n\n"
        f"Пост из Telegram-канала:\n\"\"\"\n{clip_for_filter(text)}\n\"\"\"\n\n"
        "Ответь СТРОГО одним словом: INTERESTING или SKIP. /no_think"
    )
    ans = llm.chat(prompt, temperature=0, max_tokens=24, timeout=180, raise_on_error=True)
    # если модель всё же «задумалась» — срезаем <think>…</think>, чтобы слово
    # INTERESTING/SKIP внутри рассуждения не сбило разбор (как уже делаем в extract_seeds)
    ans = re.sub(r"<think>.*?</think>", "", ans, flags=re.DOTALL).strip().upper()
    if "INTERESTING" in ans:
        return True
    if "SKIP" in ans:
        return False
    return True   # непонятный ответ модели → на ревью, пост НЕ теряем

def extract_seeds(text):
    """Из интересного поста достаём 1-3 ОБЩИХ поисковых запроса для topic_finder.

    Раньше модель возвращала названия свежих моделей и чипов — по ним частотность
    нулевая. Теперь явно требуем обобщение до категории/задачи/проблемы, а годы и
    номера версий отсекаем ещё и постфильтром."""
    prompt = (
        "Ниже пост из технологического канала. Придумай 1-3 коротких поисковых "
        "запроса (2-4 слова), которые люди РЕГУЛЯРНО набирают в поиске по теме "
        "этого поста.\n\n"
        "ГЛАВНОЕ ПРАВИЛО: обобщай. Не бери название конкретной новинки, модели, "
        "версии или чипа — по ним поиска почти нет. Поднимись на уровень выше: "
        "категория устройства, задача пользователя, проблема, сравнение.\n\n"
        "Примеры обобщения:\n"
        "- пост про «Galaxy Z Fold8» -> [\"складной смартфон\", \"какой самсунг купить\"]\n"
        "- пост про «Snapdragon 8 Elite Gen 6» -> [\"мощный процессор смартфона\", \"какой процессор лучше\"]\n"
        "- пост про «iQOO 16T с вентилятором» -> [\"игровой смартфон\", \"перегрев телефона\"]\n"
        "- пост про «12 гб памяти в MacBook» -> [\"сколько памяти нужно ноутбуку\", \"какой macbook выбрать\"]\n"
        "- пост про новую функцию Windows -> [\"настройка windows 11\", \"скрытые функции windows\"]\n"
        "- пост про кражу криптовалюты с биржи -> [\"как хранить криптовалюту\", \"безопасность криптокошелька\"]\n\n"
        "Запрещено: годы (2025, 2026), номера версий и моделей, кодовые названия "
        "чипов, имена каналов, слова «новый» и «свежий».\n"
        "Пиши по-русски, строчными буквами.\n\n"
        f"Пост:\n\"\"\"\n{text[:1500]}\n\"\"\"\n\n"
        "Верни СТРОГО JSON-массив строк, без пояснений. /no_think"
    )
    ans = llm.chat(prompt, temperature=0, max_tokens=120, timeout=120)
    ans = re.sub(r"<think>.*?</think>", "", ans, flags=re.DOTALL)
    start, end = ans.find("["), ans.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        arr = json.loads(ans[start:end + 1])
    except Exception:
        return []

    out = []
    for x in arr:
        s = " ".join(str(x).strip().lower().split())
        if not s:
            continue
        words = s.split()
        if len(words) < 2 or len(words) > 5:
            continue                      # однословные и простыни бесполезны
        if re.search(r"20[2-9]\d", s):
            continue                      # затравки с годом стабильно дают 0 строк
        if s not in out:
            out.append(s)
    return out[:3]

async def main(dry_run=None, hours=None, progress=None, cancel=None):
    """Возвращает текст итогового сообщения (или None, если слать нечего).

    ВАЖНО: отсюда НЕЛЬЗЯ звать telegram.send_message — это блокирующий requests
    внутри работающего цикла asyncio, прогон подвисал намертво. Итог отправляется
    вызывающим кодом после закрытия цикла.

    Аргументы нужны окну, из командной строки они не передаются:
    - dry_run и hours: None означает «взять из командной строки». Окно ОБЯЗАНО
      передавать их явно: в его sys.argv нет --dry-run, и режим молча оказался
      бы боевым;
    - progress: функция progress(событие, **данные) для показа хода работы;
    - cancel: объект с методом is_set() (например, threading.Event). Отмена
      проверяется между постами и между каналами, поэтому курсор остаётся
      на последнем успешно отправленном посте и ничего не теряется.
    """
    if dry_run is None:
        dry_run = "--dry-run" in sys.argv
    if hours is None:
        hours = _arg_hours(dry_run)
    progress = progress or (lambda event, **data: None)
    cancelled = (lambda: cancel is not None and cancel.is_set())
    if dry_run:
        logger.info("=== ТЕСТОВЫЙ РЕЖИМ (dry-run): без пересылки и без записи state ===")
        logger.info(f"=== Смотрю последние {hours} ч по всем каналам, state игнорирую ===")
        logger.info("=== (окно меняется флагом, например: python digest.py --dry-run --hours 6) ===")
    else:
        logger.info(f"=== Проверка каналов запущена (окно первого запуска: {hours} ч) ===")

    state = load_state()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    target = await client.get_entity(TARGET)

    found = 0
    checked = 0
    skipped = 0
    errors = 0
    unreachable = []          # каналы, которые не открылись вообще
    renamed = []              # каналы, сменившие ссылку (нашлись по запомненному id)
    llm_dead = False          # модель недоступна -> прекращаем весь прогон
    fresh_seeds = []          # свежие затравки для topic_finder (синергия)
    stopped = False           # прогон остановлен кнопкой отмены

    progress("start", dry_run=dry_run, hours=hours, total=len(CHANNELS))

    for number, ch in enumerate(CHANNELS, 1):
        if cancelled():
            stopped = True
            logger.info("=== Остановлено кнопкой: непроверенные каналы дочитаем в следующий прогон ===")
            break
        progress("channel", number=number, total=len(CHANNELS), name=str(ch))
        try:
            entity, note = await _open_channel(client, ch, state)
        except FloodWaitError as e:
            wait = min(int(getattr(e, "seconds", 60)) + 5, FLOOD_WAIT_CAP)
            logger.warning(f"[!] FloodWait {wait} с на {ch} — жду и пробую ещё раз...")
            await asyncio.sleep(wait)
            try:
                entity, note = await _open_channel(client, ch, state)
            except Exception as e2:
                entity, note = None, str(e2)
        if entity is None:
            unreachable.append((str(ch), str(note)))
            logger.warning(f"[!] Не удалось открыть {ch}: {note}")
            continue
        if note:
            renamed.append((str(ch), note))
            logger.info(f"[~] {ch} по ссылке не открылся, но нашёлся по id. Новая ссылка: {note}")

        # ключ состояния — username канала; при первом запуске переносим со старого ключа-URL
        key = _chan_key(ch, entity)
        if not dry_run and _migrate_key(state, str(ch), key):
            logger.info(f"   ↪ состояние перенесено: {ch} -> {key}")
        # канал сменил ник: тащим курсор и реестр отправленного со старого ключа,
        # иначе он считается новым и перечитывает окно в 28 часов с дублями
        old_key = _chan_memo(state, ch).get("key")
        if not dry_run and old_key and old_key != key and _migrate_key(state, old_key, key):
            logger.info(f"   ↪ канал сменил ник: {old_key} -> {key}, состояние перенесено")
        if not dry_run:
            _remember_chan(state, ch, entity, key)

        # dry-run: игнорируем состояние, смотрим окно hours (повторяемо)
        last_id = 0 if dry_run else state.get(key, 0)
        username = getattr(entity, "username", None)
        title = getattr(entity, "title", str(ch))
        max_id = last_id
        committed_id = last_id   # докуда безопасно продвинуть состояние (только успешно обработанное)
        # реестр уже пересланных постов этого канала — вторая линия защиты от дублей
        sent = set(state.get(SENT_KEY, {}).get(key, []))

        # --- собираем сообщения, группируя альбомы по grouped_id ---
        groups = {}     # ключ -> [сообщения]
        order = []      # порядок постов
        try:
            async for msg in client.iter_messages(entity, limit=200):
                if last_id and msg.id <= last_id:
                    break
                if not last_id and msg.date < cutoff:
                    break
                if msg.id > max_id:
                    max_id = msg.id
                # альбом — общий grouped_id; одиночное — свой id
                gkey = f"g{msg.grouped_id}" if msg.grouped_id else f"s{msg.id}"
                if gkey not in groups:
                    groups[gkey] = []
                    order.append(gkey)
                groups[gkey].append(msg)
        except FloodWaitError as e:
            # Telegram просит подождать. Раньше это ловилось общим except и канал
            # молча выпадал из прогона.
            wait = min(int(getattr(e, "seconds", 60)) + 5, FLOOD_WAIT_CAP)
            logger.warning(f"[{title}] FloodWait {wait} с при чтении — жду, канал дочитаю в следующий прогон.")
            await asyncio.sleep(wait)
            continue
        except Exception as e:
            errors += 1
            logger.error(f"[{title}] [!] ошибка чтения канала: {e}")
            continue

        posts = [groups[k] for k in order]   # каждый пост = список сообщений
        logger.info(f"[{title}] новых постов: {len(posts)} — анализирую...")

        # --- от старых к новым ---
        for group in reversed(posts):
            if cancelled():
                # чекпоинт: committed_id стоит на последнем успешно обработанном
                # посте, поэтому остановка здесь ничего не теряет
                stopped = True
                logger.info("   ⏹ остановлено кнопкой — этот и следующие посты дочитаем позже")
                break
            text = next((m.message for m in group if m.message), "")   # подпись из группы
            has_media = any(m.media for m in group)
            post_max = max(m.id for m in group)

            if text.strip():
                try:
                    interesting = is_interesting(text)
                except LLMUnavailable as e:
                    # модель лежит — нет смысла ждать по 9 минут на каждом из 54 каналов
                    errors += 1
                    llm_dead = True
                    logger.error(f"   [!] МОДЕЛЬ НЕДОСТУПНА: {e}")
                    logger.error("   [!] Прерываю весь прогон. Непроверенные посты дошлём в следующий раз.")
                    break
                except Exception as e:
                    # ОШИБКА != SKIP: не теряем пост и не двигаем состояние дальше
                    errors += 1
                    ids_err = sorted(m.id for m in group)
                    logger.error(f"   [!] ошибка проверки поста (id {ids_err}): {e}")
                    if dry_run:
                        continue          # в тесте просто пропускаем этот пост
                    logger.error("   [!] стоп по каналу — дошлём этот и следующие посты в след. прогон")
                    break                 # чекпоинт: committed_id остаётся на последнем удачном
            else:
                interesting = has_media   # нет подписи, но есть медиа → на ревью (особое правило)

            checked += 1
            # счётчики отдаём фактические: found растёт только после доставки,
            # и угадывать его заранее нельзя — окно показывало бы неправду
            progress("counters", checked=checked, found=found, skipped=skipped, errors=errors)

            if dry_run:
                # только печатаем решение — ничего не шлём и не сохраняем
                verdict = "INTERESTING" if interesting else "SKIP"
                preview = " ".join(text.split())[:80] or "(без текста, есть медиа)"
                logger.info(f"   {verdict:<11} | {preview}")
                if interesting:
                    found += 1
                else:
                    skipped += 1
                continue

            if not interesting:
                skipped += 1
                committed_id = post_max      # skip обработан успешно — можно продвинуть
                continue

            # защита от повторов: этот пост уже пересылали (прогон прервался/наложился) —
            # не шлём второй раз, просто двигаем курсор дальше
            if post_max in sent:
                logger.info(f"   ↩ дубль (id {post_max} уже отправлялся) — пропускаю")
                committed_id = post_max
                continue

            found += 1
            # синергия: копим поисковые фразы из интересного текста (с лимитом-запасом)
            if EXTRACT_SEEDS and text.strip() and len(fresh_seeds) < 60:
                fresh_seeds.extend(extract_seeds(text))
            ids = sorted(m.id for m in group)
            logger.info(f"   + интересное (id {ids}) — пересылаю медиа: {len(ids)}")

            delivered = False
            try:
                # список ID одной группы → Telegram воссоздаёт альбом целиком
                await client.forward_messages(target, ids, entity, silent=True)
                delivered = True
            except FloodWaitError as e:
                wait = min(int(getattr(e, "seconds", 30)) + 5, FLOOD_WAIT_CAP)
                logger.warning(f"   [!] FloodWait {wait} с при пересылке — жду и повторяю...")
                await asyncio.sleep(wait)
                try:
                    await client.forward_messages(target, ids, entity, silent=True)
                    delivered = True
                except Exception as e2:
                    logger.warning(f"   [!] повтор пересылки не прошёл ({e2})")
            except Exception as e:
                logger.warning(f"   [!] репост не прошёл ({e}); шлю текстом")

            if not delivered:
                try:
                    link = ("https://t.me/" + username + "/" + str(ids[0])) if username else ""
                    await client.send_message(
                        target, f"📌 {title}\n\n{text[:1500]}\n\n{link}", silent=True
                    )
                    delivered = True
                except Exception as e2:
                    # и репост, и текст не ушли — это ошибка доставки, не теряем пост
                    found -= 1
                    errors += 1
                    logger.error(f"   [!] и текстом не ушло ({e2}); стоп по каналу — дошлём позже")
                    break

            committed_id = post_max          # доставлено — можно продвинуть
            sent.add(post_max)               # запомнили, что этот пост уже ушёл
            # сохраняем СРАЗУ после отправки: если прогон прервётся, уже пересланный
            # пост не уйдёт повторно в следующий раз
            state[key] = committed_id
            state.setdefault(SENT_KEY, {})[key] = sorted(sent)[-SENT_KEEP:]
            save_state(state)

        # состояние двигаем только на успешно обработанное (в тесте не трогаем совсем)
        if not dry_run:
            state[key] = committed_id
            state.setdefault(SENT_KEY, {})[key] = sorted(sent)[-SENT_KEEP:]
            save_state(state)

        progress("counters", checked=checked, found=found, skipped=skipped, errors=errors)

        if llm_dead:
            break                            # выходим из цикла по каналам
        if stopped:
            break                            # отмена: состояние канала уже сохранено выше

    if dry_run:
        logger.info(f"=== Готово (dry-run). Проверено {checked}, INTERESTING {found}, SKIP {skipped}, Ошибок {errors}.")
        if renamed:
            logger.info(f"=== Сменили ссылку ({len(renamed)}) — поправь CHANNELS:")
            for c, link in renamed:
                logger.info(f"      {c} -> {link}")
        if unreachable:
            logger.info(f"=== НЕ ОТКРЫЛИСЬ ({len(unreachable)}):")
            for c, err in unreachable:
                logger.info(f"      {c}: {err}")
        if stopped:
            logger.info("=== Прогон остановлен кнопкой. ===")
        logger.info("=== Ничего не переслано, state.json не изменён. ===")
        await client.disconnect()
        progress("done", checked=checked, found=found, skipped=skipped,
                 errors=errors, stopped=stopped)
        return None

    # синергия: сохраняем свежие затравки для topic_finder
    if fresh_seeds:
        total = seeds.add_fresh_seeds(fresh_seeds)
        logger.info(f"Свежих затравок для topic_finder: +{len(fresh_seeds)} (в базе {total})")

    # отключаемся ДО отправки итога: блокирующий requests при живом Telethon вешал прогон
    logger.info("Отключаюсь от Telegram...")
    await client.disconnect()
    logger.info(f"=== Готово. Переслано постов: {found} ===")

    final_msg = (
        "✅ Дайджест готов\n"
        f"📥 Проверено постов: {checked}\n"
        f"📌 Интересных: {found}\n"
        f"🚫 Пропущено: {skipped}"
    )
    if errors:
        final_msg += f"\n⚠️ Ошибок: {errors} — дошлю в следующий прогон"
    if renamed:
        final_msg += f"\n🔁 Сменили ссылку ({len(renamed)}) — работаю по id, поправь список:"
        for c, link in renamed[:10]:
            final_msg += f"\n   {c} → {link}"
    if unreachable:
        final_msg += f"\n⛔ Не открылись ({len(unreachable)}):"
        for c, err in unreachable[:10]:
            final_msg += f"\n   {c} — {err[:90]}"
    if llm_dead:
        final_msg += "\n⛔ Прогон прерван: локальная модель не отвечает"
    if stopped:
        final_msg += "\n⏹ Прогон остановлен кнопкой — остальное дочитаем в следующий раз"
    progress("done", checked=checked, found=found, skipped=skipped,
             errors=errors, stopped=stopped)
    return final_msg

if __name__ == "__main__":
    logs.setup("digest")      # весь вывод дублируется в logs/<дата>_digest.log

    # dry-run безвреден (ничего не шлёт/не пишет) — его не блокируем;
    # боевой прогон оборачиваем в lock, чтобы не пересеклись два запуска
    if "--dry-run" in sys.argv:
        asyncio.run(main())
    elif not acquire_lock():
        logger.warning("[!] Уже идёт другой прогон (свежий lock-файл) — выхожу, чтобы не задвоить посты.")
    else:
        summary = None
        try:
            summary = asyncio.run(main())
        finally:
            release_lock()
        # финальный сигнал шлём ПОСЛЕ закрытия цикла asyncio и отключения Telethon —
        # именно здесь прогон раньше вставал намертво
        if summary:
            logger.info("Отправляю итог боту...")
            ok = telegram.send_message(summary)
            if ok:
                logger.info("Итог отправлен.")
            else:
                logger.warning("[!] Итог отправить не удалось.")

    # явный выход: не ждём недозакрытые async-генераторы iter_messages
    # (из них мы всегда выходим через break, и процесс мог не завершиться)
    sys.exit(0)