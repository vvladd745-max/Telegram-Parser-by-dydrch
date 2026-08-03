"""Локальная модель в LM Studio: поднять перед проверкой, отпустить после.

Единственное место в проекте, которое знает про команду lms. Раньше эта
логика жила в батниках run.bat и run_all.bat; батников в программе нет,
и она переехала сюда.

Главное правило: УБИРАЕМ ЗА СОБОЙ, НО ТОЛЬКО СВОЁ. Если человек сам открыл
LM Studio и загрузил модель — работаем на готовом и ничего не трогаем на
выходе. Батник выгружал всё подряд, и это было допустимо, пока он запускался
вручную и в одиночку. Программа, которая может проснуться по расписанию
посреди чужой работы, так вести себя не должна.

Что выяснено про lms опытным путём (проверено на живой машине):
  * `lms.exe` приезжает вместе с LM Studio и лежит в
    %USERPROFILE%\\.lmstudio\\bin\\lms.exe. На PATH полагаться нельзя:
    туда он попадает только после отдельной команды, и у коллеги его там
    может не быть;
  * `lms ps --json` печатает список загруженных моделей в JSON — состояние
    читается надёжно, без разбора человеческого текста;
  * повторная загрузка той же модели возвращает код 1 и пишет
    «A model with identifier ... already exists». Это НЕ ошибка;
  * `lms unload --all` и `lms server stop` можно звать повторно: они
    не ругаются, когда убирать уже нечего.

Если lms не нашёлся — это не повод срывать проверку. Возможно, LM Studio
уже запущен руками. Тогда молча идём дальше: не достучимся до модели —
об этом скажет сама проверка, и скажет понятнее.
"""
import json
import os
import re
import subprocess
from urllib.parse import urlparse

from . import settings
from .logs import logger

# Ключи загрузки взяты из run.bat один в один. Контекст 65536 подобран под
# эту модель, менять только с проверкой качества отбора.
CONTEXT_LENGTH = 65536
GPU_OFFLOAD = "max"

# Загрузка модели с холодного диска занимает заметное время, но не вечность.
LOAD_TIMEOUT = 600
SHORT_TIMEOUT = 120

# Сообщение, по которому lms сообщает, что модель уже в памяти.
ALREADY_LOADED = "already exists"

# Убирает управляющие последовательности: lms рисует крутилку прогресса,
# и без чистки в журнал человека попадёт каша из служебных символов.
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


class LMStudioError(Exception):
    """Не удалось подготовить модель. Текст написан для человека."""


def _exe():
    """Путь к lms.exe или пустая строка.

    Сначала место, куда его кладёт сам LM Studio, потом PATH — на случай,
    если человек ставил LM Studio куда-то ещё.
    """
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    known = os.path.join(home, ".lmstudio", "bin", "lms.exe")
    if os.path.exists(known):
        return known
    from shutil import which
    return which("lms") or ""


def available():
    """Можем ли мы вообще управлять LM Studio."""
    return bool(_exe())


def _run(args, timeout=SHORT_TIMEOUT):
    """Вызов lms. Возвращает (код возврата, вывод без служебных символов).

    CREATE_NO_WINDOW обязателен: без него в сборке без консоли на экране
    мигает чёрное окно на каждую команду.
    """
    exe = _exe()
    if not exe:
        return None, ""
    env = dict(os.environ)
    env["NO_COLOR"] = "1"          # просим lms не раскрашивать вывод
    try:
        done = subprocess.run(
            [exe] + list(args),
            capture_output=True, timeout=timeout, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise LMStudioError(
            f"LM Studio не ответил за {timeout // 60} мин на команду «{' '.join(args)}». "
            "Похоже, он завис — закройте и откройте его вручную.") from None
    except OSError as e:
        raise LMStudioError(f"Не удалось запустить LM Studio: {e}.") from None

    raw = (done.stdout or b"") + (done.stderr or b"")
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return done.returncode, ANSI.sub("", text).strip()


# ---------- что сейчас происходит ----------

def server_running():
    code, text = _run(["server", "status"])
    if code is None:
        return False
    return "not running" not in text.lower()


def loaded_models():
    """Опознаватели моделей, лежащих сейчас в памяти. Пустой список — ничего нет."""
    code, text = _run(["ps", "--json"])
    if code is None or code != 0:
        return []
    # в выводе перед JSON может оказаться приветствие — берём с первой скобки
    start = text.find("[")
    if start < 0:
        return []
    try:
        items = json.loads(text[start:])
    except json.JSONDecodeError:
        logger.warning("   [!] Не разобрал ответ LM Studio о загруженных моделях.")
        return []
    return [str(item.get("identifier") or "") for item in items if isinstance(item, dict)]


def is_loaded(name):
    return str(name) in loaded_models()


def local_model():
    """Работаем ли мы с моделью на этом компьютере.

    Если в настройках указан облачный адрес, поднимать локальный LM Studio
    бессмысленно и вредно: съест память и ничего не даст.
    """
    try:
        host = (urlparse(str(settings.get("model.url", ""))).hostname or "").lower()
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "::1", "")


# ---------- подготовка и уборка ----------

def prepare():
    """Поднять LM Studio и загрузить модель. Вернуть, что именно мы сделали.

    Возвращается словарь для release(): по нему видно, что убирать. Пустой
    словарь означает «мы ничего не меняли» — и убирать тогда нечего.

    Молча ничего не делаем в двух случаях: модель не локальная и lms не
    найден. Оба — не ошибка: проверка пойдёт дальше и сама скажет, если
    до модели не достучаться.
    """
    done = {"server": False, "model": ""}
    if not local_model():
        logger.info("Модель не на этом компьютере — LM Studio не трогаю.")
        return done
    if not available():
        logger.info("LM Studio на этом компьютере не найден — "
                    "рассчитываю, что модель уже отвечает.")
        return done

    name = str(settings.get("model.name", "") or "").strip()
    if not name:
        raise LMStudioError("В настройках не указано имя модели — "
                            "непонятно, что загружать в LM Studio.")

    if not server_running():
        logger.info("Запускаю LM Studio...")
        code, text = _run(["server", "start"])
        if code != 0:
            raise LMStudioError(
                "Не удалось запустить LM Studio. " + (text.splitlines()[0] if text else ""))
        done["server"] = True
    else:
        logger.info("LM Studio уже запущен.")

    if is_loaded(name):
        logger.info(f"Модель {name} уже в памяти — загружать заново не нужно.")
        return done

    logger.info(f"Загружаю модель {name}. Это может занять несколько минут...")
    code, text = _run(
        ["load", name, "-y", "--gpu", GPU_OFFLOAD,
         "--context-length", str(CONTEXT_LENGTH), "--identifier", name],
        timeout=LOAD_TIMEOUT)

    if code != 0 and ALREADY_LOADED in text.lower():
        # кто-то успел загрузить её между нашей проверкой и загрузкой —
        # результат ровно тот, что нужен, поэтому это не ошибка
        logger.info(f"Модель {name} уже в памяти — загружать заново не нужно.")
        return done
    if code != 0:
        raise LMStudioError(
            f"LM Studio не смог загрузить модель {name}. "
            + (text.splitlines()[-1] if text else "Причину он не назвал."))

    done["model"] = name
    logger.info("Модель загружена.")
    return done


def release(done):
    """Убрать за собой то, что подняли сами.

    Чужое не трогаем: модель, которая была в памяти до нас, там и останется,
    и сервер, запущенный человеком, продолжит работать. Ошибки уборки не
    выносим наружу — проверка к этому моменту уже прошла, и валить её из-за
    неубранной модели нельзя.
    """
    if not done:
        return
    try:
        if done.get("model"):
            logger.info("Выгружаю модель из памяти.")
            _run(["unload", done["model"]])
        if done.get("server"):
            logger.info("Останавливаю LM Studio.")
            _run(["server", "stop"])
    except LMStudioError as e:
        logger.warning(f"   [!] Не удалось освободить память: {e}")
    except Exception as e:
        logger.warning(f"   [!] Не удалось освободить память: {e}")
