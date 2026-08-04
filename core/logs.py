"""Журнал работы агентов на loguru.

При запуске по расписанию окно закрывается и разбирать нечего.
logs.setup("digest") в начале работы — и все сообщения уходят ещё и в
<ГГГГ-ММ-ДД>_<имя>.log в папке логов, которую указывает core.paths.

В собранном .exe без консоли sys.stdout и sys.stderr равны None. Поэтому
файл — единственный обязательный канал, а консоль подключается, только если
писать действительно есть куда. Обычный print при этом не теряется: он уходит
не в поток, а в сам журнал, и оттуда достаётся всем получателям.
"""
import sys, os, datetime, atexit, threading

from loguru import logger

from . import paths

KEEP_DAYS = 30      # логи старше — удаляем (штатный retention loguru)

# В консоли — голый текст сообщения: прогоны сравниваются глазами, префиксы мешают.
CONSOLE_FORMAT = "{message}"
# В файле наоборот: без времени и уровня старый лог бесполезен.
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {message}"

_console_id = None      # id консольного обработчика loguru
_file_id = None         # id файлового обработчика loguru
_mirror = None          # подменённый sys.stdout, пока зеркало print включено
_mirror_prev = None     # что стояло в sys.stdout до подмены (бывает и None)


class _PrintToLog:
    """Обычный print уходит в журнал, а журнал раздаёт строку всем получателям:
    в файл, на экран и в окно программы, если оно подписано на прогон.

    Нужен ради topic_finder: он пишет только print, и без этого его не слышно
    вовсе. Раньше зеркало оборачивало настоящий sys.stdout и писало в файл
    само — а в собранной программе без консоли sys.stdout равен None,
    оборачивать нечего, и зеркало не включалось. При пустом sys.stdout print
    молча ничего не делает, поэтому весь вывод инструмента пропадал целиком:
    поиск тем работал полторы минуты и не сказал ни слова.

    Записи самого loguru сюда не возвращаются: его консольный обработчик
    держит поток, взятый при подключении, и подмену sys.stdout не видит —
    поэтому строки не удваиваются и петли не возникает.
    """

    def __init__(self):
        self._buf = ""

    def write(self, data):
        # print зовёт write несколько раз: отдельно текст, отдельно перевод
        # строки. Без сборки по строкам каждый кусок стал бы своей записью.
        self._buf += str(data)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(data)

    def flush(self):
        """Отдаёт хвост без перевода строки — иначе последняя строка пропала бы."""
        if self._buf:
            line, self._buf = self._buf, ""
            self._emit(line)

    @staticmethod
    def _emit(line):
        line = line.rstrip()
        if line:      # пустые строки-отбивки в журнал не тащим
            logger.info(line)

    def isatty(self):
        return False


def _install_print_mirror():
    """Направляет обычный print в журнал.

    Работает и без консоли: получателям строки раздаёт loguru, а не поток."""
    global _mirror, _mirror_prev
    if _mirror is not None:
        return
    _mirror_prev = sys.stdout
    _mirror = _PrintToLog()
    sys.stdout = _mirror
    atexit.register(_remove_print_mirror)


def _remove_print_mirror():
    """Возвращает sys.stdout на место. Зовётся при выходе."""
    global _mirror, _mirror_prev
    if _mirror is not None:
        _mirror.flush()
        if sys.stdout is _mirror:
            sys.stdout = _mirror_prev
    _mirror = None
    _mirror_prev = None


def _console_stream():
    """Поток для вывода на экран или None, если консоли нет.

    Именно этот случай — .exe без консоли: там sys.stdout и sys.stderr
    равны None, и писать некуда."""
    for stream in (sys.stderr, sys.stdout):
        if stream is not None and hasattr(stream, "write"):
            return stream
    return None


def _add_console():
    """Подключает вывод на экран, если экран есть. Второй раз не подключает."""
    global _console_id
    if _console_id is not None:
        return
    stream = _console_stream()
    if stream is None:
        return
    # записи о падении в консоль не отдаём: следом отработает прежний обработчик
    # исключений и напечатает ту же трассировку сам — иначе она была бы дважды
    _console_id = logger.add(stream, format=CONSOLE_FORMAT, level="DEBUG",
                             colorize=False, backtrace=False, diagnose=False,
                             filter=lambda record: not record["extra"].get("crash"))


# Родной обработчик loguru пишет в stderr со своими префиксами — он нам не нужен.
logger.remove()
_add_console()


_hooks_installed = False


def _install_excepthooks():
    """Записывает в журнал падения, которые никто не поймал.

    Без этого трассировка уходит только в sys.stderr, а в сборке без консоли
    stderr равен None — падение не оставит вообще никакого следа, и разбираться
    с жалобой будет не по чему.

    Прежние обработчики вызываются следом, поэтому на экране всё как раньше.
    Второй раз перехватчик не ставится: иначе при повторном setup он навернулся
    бы сам на себя и писал бы каждое падение дважды.
    """
    global _hooks_installed
    if _hooks_installed:
        return
    prev_sys_hook = sys.excepthook
    prev_thread_hook = threading.excepthook

    def to_log(exc_type, exc_value, exc_tb, where=""):
        logger.bind(crash=True).opt(exception=(exc_type, exc_value, exc_tb)) \
              .error(f"[!] Неперехваченная ошибка{where}")

    def sys_hook(exc_type, exc_value, exc_tb):
        # Ctrl+C — не падение, в журнал он не нужен
        if not issubclass(exc_type, KeyboardInterrupt):
            to_log(exc_type, exc_value, exc_tb)
        prev_sys_hook(exc_type, exc_value, exc_tb)

    def thread_hook(args):
        """Падение рабочего потока. В будущем приложении прогон дайджеста будет
        жить именно в таком потоке, и без этого его падение потерялось бы."""
        if not issubclass(args.exc_type, KeyboardInterrupt):
            name = getattr(args.thread, "name", "")
            to_log(args.exc_type, args.exc_value, args.exc_traceback,
                   f" в потоке {name}" if name else "")
        prev_thread_hook(args)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
    _hooks_installed = True


def setup(name, mirror_print=True):
    """Включает запись журнала в файл. Возвращает путь к логу (или "" при неудаче).

    mirror_print — направлять ли обычный вывод print в журнал. По умолчанию
    да: часть агентов пишет только print, и без этого их не слышно вовсе.
    Работает в том числе в сборке без консоли, где sys.stdout равен None.

    Имя и первый аргумент менять нельзя: setup вызывает не только digest.
    """
    global _file_id
    try:
        logs_dir = paths.logs_dir()
        os.makedirs(logs_dir, exist_ok=True)

        # дату в имени подставляет сам loguru: по этому же шаблону он потом
        # ищет старые файлы, чтобы применить retention
        pattern = os.path.join(logs_dir, "{time:YYYY-MM-DD}_" + name + ".log")
        day = datetime.date.today().isoformat()
        path = os.path.join(logs_dir, f"{day}_{name}.log")

        # разделитель запусков: за день в один файл пишет несколько прогонов
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp} запуск {name} =====\n")

        if _file_id is not None:
            logger.remove(_file_id)
        _file_id = logger.add(pattern, format=FILE_FORMAT, level="DEBUG",
                              encoding="utf-8", retention=f"{KEEP_DAYS} days",
                              backtrace=False, diagnose=False)
        _add_console()
        # зеркало ставим последним: к этому моменту loguru уже держит
        # настоящий поток, и подмена sys.stdout его не касается
        if mirror_print:
            _install_print_mirror()
        _install_excepthooks()
        return path
    except Exception as e:
        logger.warning(f"   [!] не смог включить файловый лог: {e}")
        return ""
