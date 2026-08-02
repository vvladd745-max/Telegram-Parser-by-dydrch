"""Журнал работы агентов на loguru.

При запуске по расписанию окно закрывается и разбирать нечего.
logs.setup("digest") в начале работы — и все сообщения уходят ещё и в
<ГГГГ-ММ-ДД>_<имя>.log в папке логов, которую указывает core.paths.

Почему подмена sys.stdout стала условной: в собранном .exe без консоли
sys.stdout равен None, и безусловная подмена падает на первой же строке.
Поэтому файл — единственный обязательный канал, а консоль и зеркало обычного
вывода подключаются, только если писать действительно есть куда.
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
_mirror_file = None     # файл, в который зеркало пишет


class _MirrorStdout:
    """Обычный print уходит и на экран, и в файл журнала.

    Нужен ради topic_finder: он пишет только print, и без зеркала его лог
    состоял бы из одной шапки запуска. Записи loguru сюда не попадают: его
    консольный обработчик держит поток, взятый при подключении, и подмену
    sys.stdout уже не видит — поэтому строки не удваиваются.
    """

    def __init__(self, stream, fh):
        self._stream = stream
        self._fh = fh

    def write(self, data):
        self._stream.write(data)
        self._stream.flush()
        try:
            self._fh.write(data)
            self._fh.flush()
        except Exception:
            pass          # проблемы с логом не должны ронять агента
        return len(data)

    def flush(self):
        for target in (self._stream, self._fh):
            try:
                target.flush()
            except Exception:
                pass

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()

    def __getattr__(self, name):
        # всё остальное (encoding, buffer и прочее) отдаёт настоящий поток
        return getattr(self._stream, name)


def _install_print_mirror(path):
    """Включает зеркало print в файл журнала.

    Ничего не делает, если писать некуда: в .exe без консоли sys.stdout равен
    None, и подменять его нельзя — на этом и падал старый код."""
    global _mirror, _mirror_file
    if _mirror is not None:
        return
    stream = sys.stdout
    if stream is None or not hasattr(stream, "write"):
        return
    try:
        fh = open(path, "a", encoding="utf-8")
    except Exception:
        return
    _mirror_file = fh
    _mirror = _MirrorStdout(stream, fh)
    sys.stdout = _mirror
    atexit.register(_remove_print_mirror)


def _remove_print_mirror():
    """Возвращает sys.stdout на место и закрывает файл. Зовётся при выходе."""
    global _mirror, _mirror_file
    if _mirror is not None and sys.stdout is _mirror:
        sys.stdout = _mirror._stream
    _mirror = None
    if _mirror_file is not None:
        try:
            _mirror_file.close()
        except Exception:
            pass
        _mirror_file = None


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

    mirror_print — дублировать ли в тот же файл обычный вывод print. По
    умолчанию да: часть агентов пишет только print, и без этого их лог пуст.
    Зеркало включается ТОЛЬКО при живой консоли, поэтому в сборке без неё
    ничего не подменяется.

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
            _install_print_mirror(path)
        _install_excepthooks()
        return path
    except Exception as e:
        logger.warning(f"   [!] не смог включить файловый лог: {e}")
        return ""
