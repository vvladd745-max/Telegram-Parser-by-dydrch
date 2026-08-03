"""Расписание проверки — задача в Планировщике заданий Windows.

Единственное место в проекте, которое знает про schtasks. Никто больше
команд планировщика не собирает: если завтра расписание переедет на другой
механизм, править надо будет только здесь.

Почему задача описывается через XML, а не короткими ключами schtasks.
Ключей /SC DAILY /ST 08:00 хватило бы, но у такой задачи нет главного:
«запустить при первой возможности, если время пропущено». Ноутбук журналиста
в 8 утра чаще выключен или спит, и задача без этого свойства просто молчит,
а человек думает, что программа сломана. Через XML это включается
(StartWhenAvailable), а заодно снимается запрет на работу от батареи.

Что здесь НЕ хранится: время и дни. Они живут в settings.json, в разделе
schedule, и окно берёт их оттуда. Планировщик — исполнитель, а не память:
читать время обратно из него пришлось бы разбором вывода в кодировке
консоли, а это ровно тот сорт кода, который ломается на чужой машине.
Проверяется у планировщика только одно — есть задача или нет.
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from . import paths, settings
from .logs import logger

# Имя задачи в планировщике. Менять нельзя: по нему задача ищется, обновляется
# и удаляется. После смены старая задача осталась бы висеть навсегда.
TASK_NAME = "Парсер Telegram-каналов — проверка"

# Дни недели в порядке datetime.weekday(): понедельник — 0.
# Ключ хранится в настройках, тег уходит в XML, название видит человек.
DAYS = (
    ("mon", "Monday", "Пн"),
    ("tue", "Tuesday", "Вт"),
    ("wed", "Wednesday", "Ср"),
    ("thu", "Thursday", "Чт"),
    ("fri", "Friday", "Пт"),
    ("sat", "Saturday", "Сб"),
    ("sun", "Sunday", "Вс"),
)
DAY_KEYS = [key for key, _, _ in DAYS]
ALL_DAYS = list(DAY_KEYS)

DEFAULT_TIME = "08:00"


class ScheduleError(Exception):
    """Планировщик не принял задачу. Текст написан для человека."""


# ---------- разбор того, что ввёл человек ----------

def parse_time(text):
    """«8:00», «08:00», «8» -> (8, 0). Мусор -> ScheduleError.

    Час и минуты возвращаются числами, потому что дальше их складывать
    с датой, а не показывать.
    """
    raw = str(text or "").strip().replace(".", ":").replace(" ", "")
    if not raw:
        raise ScheduleError("Не указано время проверки.")
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        raise ScheduleError(f"Не понимаю время «{text}». Пишите так: 08:00.") from None
    if len(parts) > 2 or not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise ScheduleError(f"Такого времени не бывает: «{text}». Пишите так: 08:00.")
    return hour, minute


def format_time(hour, minute):
    return f"{hour:02d}:{minute:02d}"


def clean_days(days):
    """Отбросить незнакомые ключи и сохранить порядок недели.

    Пустой список — это «никогда», и вызывающий код должен его заметить,
    поэтому пустоту молча не подменяем всеми днями.
    """
    chosen = {str(d).strip().lower() for d in (days or [])}
    return [key for key in DAY_KEYS if key in chosen]


def days_text(days):
    """Дни недели словами: «каждый день», «по будням» или «Пн, Ср, Пт»."""
    keys = clean_days(days)
    if not keys:
        return "ни одного дня"
    if keys == ALL_DAYS:
        return "каждый день"
    if keys == DAY_KEYS[:5]:
        return "по будням"
    if keys == DAY_KEYS[5:]:
        return "по выходным"
    names = {key: name for key, _, name in DAYS}
    return ", ".join(names[key] for key in keys)


# ---------- что хранится в настройках ----------

def current():
    """Расписание из настроек: (включено, «ЧЧ:ММ», список дней).

    Настройки могут быть испорчены руками — тогда молча возвращаем разумное
    значение по умолчанию, а не роняем окно.
    """
    enabled = bool(settings.get("schedule.enabled", False))
    try:
        hour, minute = parse_time(settings.get("schedule.time", DEFAULT_TIME))
        time_text = format_time(hour, minute)
    except ScheduleError:
        time_text = DEFAULT_TIME
    days = clean_days(settings.get("schedule.days", ALL_DAYS)) or ALL_DAYS
    return enabled, time_text, days


def next_run(time_text=None, days=None, now=None):
    """Когда сработает в следующий раз. None — если дни не выбраны.

    Считаем сами, а не спрашиваем планировщик: его ответ пришлось бы
    выковыривать из текста в кодировке консоли, а исходные данные
    у нас те же самые.
    """
    hour, minute = parse_time(time_text or DEFAULT_TIME)
    active = {index for index, key in enumerate(DAY_KEYS) if key in clean_days(days)}
    if not active:
        return None
    now = now or datetime.now()
    for shift in range(0, 8):
        day = (now + timedelta(days=shift)).date()
        if day.weekday() not in active:
            continue
        moment = datetime(day.year, day.month, day.day, hour, minute)
        if moment > now:
            return moment
    return None


def next_run_text(time_text=None, days=None, now=None):
    """Та же мысль словами: «сегодня в 08:00», «завтра в 08:00», «в пятницу...»."""
    moment = next_run(time_text, days, now)
    if moment is None:
        return "никогда — не выбрано ни одного дня"
    today = (now or datetime.now()).date()
    shift = (moment.date() - today).days
    when = moment.strftime("%H:%M")
    if shift == 0:
        return f"сегодня в {when}"
    if shift == 1:
        return f"завтра в {when}"
    weekday = ("в понедельник", "во вторник", "в среду", "в четверг",
               "в пятницу", "в субботу", "в воскресенье")[moment.weekday()]
    return f"{weekday} в {when}"


# ---------- что запускает планировщик ----------

def target():
    """(программа, аргументы) для задачи.

    В собранном виде это сам .exe. Из исходников — pythonw.exe, чтобы при
    срабатывании не мелькало чёрное окно консоли: задача запускается, когда
    человек работает, и посторонние окна на экране пугают.
    """
    if paths.frozen():
        return sys.executable, "--run-now"
    python = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(python):
        python = sys.executable
    script = os.path.join(paths.app_dir(), "digest", "app.py")
    return python, f'"{script}" --run-now'


# ---------- разговор с планировщиком ----------

def _text(raw):
    """Вывод schtasks в строку. Кодировка консоли на разных машинах разная,
    поэтому пробуем по очереди, а не гадаем."""
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            return (raw or b"").decode(encoding)
        except UnicodeDecodeError:
            continue
    return (raw or b"").decode("utf-8", errors="replace")


def _schtasks(*args):
    """Запуск schtasks. Возвращает (код возврата, вывод).

    CREATE_NO_WINDOW обязателен: без него в сборке без консоли на экране
    мигает чёрное окно каждый раз, когда окно программы читает расписание.
    """
    try:
        done = subprocess.run(
            ["schtasks"] + list(args),
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise ScheduleError(
            "На этом компьютере не нашёлся Планировщик заданий Windows — "
            "расписание работать не сможет.") from None
    except OSError as e:
        raise ScheduleError(f"Не удалось обратиться к планировщику Windows: {e}.") from None
    return done.returncode, (_text(done.stdout) + _text(done.stderr)).strip()


def installed():
    """Есть ли задача в планировщике. Человек мог удалить её руками, и окно
    не должно после этого уверять, что расписание работает."""
    try:
        code, _ = _schtasks("/Query", "/TN", TASK_NAME)
    except ScheduleError:
        return False
    return code == 0


def _xml(time_text, days):
    """Описание задачи для планировщика.

    Здесь важны не теги, а четыре решения:
      StartWhenAvailable  — пропущенное время не пропадает: задача сработает,
                            как только компьютер включат;
      DisallowStartIfOnBatteries=false — на ноутбуке без розетки тоже работает;
      MultipleInstancesPolicy=IgnoreNew — второй запуск поверх идущего
                            не начинается;
      ExecutionTimeLimit=PT0S — без ограничения по времени. Задача открывает
                            окно программы, и оно остаётся на экране: обычный
                            предел в три дня убил бы его прямо у человека
                            на глазах.
    """
    hour, minute = parse_time(time_text)
    keys = clean_days(days)
    if not keys:
        raise ScheduleError("Не выбрано ни одного дня недели — запускать нечего.")
    tags = {key: tag for key, tag, _ in DAYS}
    week = "".join(f"<{tags[key]} />" for key in keys)
    command, arguments = target()
    # дата начала — сегодня: планировщику нужна точка отсчёта, а день недели
    # он всё равно берёт из ScheduleByWeek
    start = datetime.now().strftime("%Y-%m-%d") + f"T{hour:02d}:{minute:02d}:00"
    user = escape(os.environ.get("USERNAME") or "")

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Проверка Telegram-каналов по расписанию. Задачу создаёт сама программа «Парсер Telegram-каналов»; удалять её вручную не нужно — снимите галочку в разделе «Расписание».</Description>
    <URI>\\{escape(TASK_NAME)}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>{week}</DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(paths.app_dir())}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def apply(time_text, days):
    """Создать или заменить задачу. Возвращает время следующего запуска словами.

    Файл описания пишется в UTF-16: schtasks не принимает XML в UTF-8 —
    ругается на «неверный формат», и понять причину по сообщению невозможно.
    """
    body = _xml(time_text, days)
    handle, path = tempfile.mkstemp(suffix=".xml", prefix="digest-schedule-")
    os.close(handle)
    try:
        with open(path, "w", encoding="utf-16") as f:
            f.write(body)
        code, output = _schtasks("/Create", "/TN", TASK_NAME, "/XML", path, "/F")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if code != 0:
        logger.warning(f"[!] Планировщик отказался принять задачу: {output}")
        raise ScheduleError(
            "Планировщик Windows не принял расписание. "
            + (output.splitlines()[0] if output else "Причину он не назвал."))

    command, arguments = target()
    logger.info(f"Расписание записано в планировщик: {time_text}, "
                f"{days_text(days)}; запускается {command} {arguments}")
    return next_run_text(time_text, days)


def remove():
    """Убрать задачу. Отсутствие задачи не ошибка: результат тот же самый."""
    if not installed():
        return False
    code, output = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if code != 0:
        logger.warning(f"[!] Не удалось убрать задачу из планировщика: {output}")
        raise ScheduleError(
            "Не удалось убрать расписание из планировщика Windows. "
            + (output.splitlines()[0] if output else ""))
    logger.info("Расписание убрано из планировщика.")
    return True


def sync(enabled, time_text, days):
    """Привести планировщик в согласие с настройками.

    Зовётся после сохранения раздела «Расписание». Возвращает строку для
    человека: что теперь будет.
    """
    if not enabled:
        remove()
        return "Проверка по расписанию выключена."
    when = apply(time_text, days)
    return f"Проверка будет запускаться {days_text(days)} в {time_text}. Ближайшая — {when}."
