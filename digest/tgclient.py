"""Вход в Telegram: рабочий поток со своим циклом asyncio.

Почему поток. Telethon асинхронный, а окно живёт в главном потоке Qt. Если
запускать корутины прямо в нём, окно замрёт на время сетевых запросов.
Поэтому здесь отдельный поток, внутри него свой цикл asyncio, а с окном он
разговаривает только сигналами. Готовых мостов между Qt и asyncio мы не берём
намеренно — решение принято в docs/roadmap.md.

Один клиент Telethon живёт весь сеанс: вход состоит из трёх обращений
(номер, код, пароль), и все они должны идти через одно соединение.
"""
import asyncio
import threading

from PySide6.QtCore import QThread, Signal

import json

from telethon import TelegramClient, utils
from telethon.tl.types import PeerChannel
from telethon.errors import (
    ApiIdInvalidError, FloodWaitError, PasswordHashInvalidError,
    PhoneCodeExpiredError, PhoneCodeInvalidError, PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.tl.functions.channels import CreateChannelRequest

from core import settings, paths
from core.channels import link_nick
from core.logs import logger

CHANNEL_ABOUT = "Сюда приходят отобранные посты. Канал создан приложением «Дайджест»."

IDS_KEY = "__ids__"      # раздел state.json с памятью по id каналов


def remembered_id(link):
    """Числовой id канала, если прогон его когда-то запомнил.

    Читаем state.json ТОЛЬКО на чтение: состоянием распоряжается digest.py,
    окно в него не пишет. Ключ памяти — ник из ссылки, тот же самый
    core.channels.link_nick, что и в прогоне: разные ключи означали бы,
    что окно и прогон видят разную память.
    """
    try:
        with open(paths.state_file(), "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    memo = (state.get(IDS_KEY) or {}).get(link_nick(link))
    return memo.get("id") if isinstance(memo, dict) else None


class SettingsIncomplete(RuntimeError):
    """Не заполнено то, без чего к Telegram даже не подключиться."""


def default_client_factory():
    """Клиент Telethon на настоящей сессии и настоящих api_id/api_hash."""
    try:
        api_id = int(settings.get("telegram.api_id") or 0)
    except (TypeError, ValueError):
        api_id = 0
    api_hash = str(settings.get_secret("telegram.api_hash") or "").strip()
    if api_id <= 0 or not api_hash:
        raise SettingsIncomplete(
            "Не заполнены api_id и api_hash. Их выдают на my.telegram.org — "
            "без них Telegram не пустит."
        )
    session = paths.session_path(settings.get("telegram.session_name"))
    paths.ensure_dirs()
    return TelegramClient(session, api_id, api_hash)


def human_error(e):
    """Ошибка Telegram человеческими словами. Подробности уходят в журнал."""
    logger.warning(f"   [!] Telegram: {type(e).__name__}: {e}")
    if isinstance(e, SettingsIncomplete):
        return str(e)
    if isinstance(e, PhoneNumberInvalidError):
        return "Telegram не узнал этот номер. Проверьте код страны и цифры."
    if isinstance(e, PhoneCodeInvalidError):
        return "Код неверный. Посмотрите ещё раз сообщение от Telegram."
    if isinstance(e, PhoneCodeExpiredError):
        return "Код устарел. Запросите новый."
    if isinstance(e, PasswordHashInvalidError):
        return "Пароль двухфакторной защиты не подошёл."
    if isinstance(e, ApiIdInvalidError):
        return "api_id и api_hash не подходят друг к другу. Проверьте их на my.telegram.org."
    if isinstance(e, FloodWaitError):
        minutes = max(1, int(getattr(e, "seconds", 60)) // 60)
        return (f"Telegram просит подождать примерно {minutes} мин — "
                "слишком много попыток подряд.")
    if isinstance(e, (ConnectionError, OSError, asyncio.TimeoutError)):
        return "Не удалось связаться с Telegram. Проверьте интернет."
    return f"Не получилось: {e}"


def display_name(me):
    """Как назвать вошедшего человека в окне."""
    if me is None:
        return "неизвестно кто"
    name = " ".join(x for x in (getattr(me, "first_name", ""),
                                getattr(me, "last_name", "")) if x).strip()
    username = getattr(me, "username", None)
    if username:
        name = f"{name} (@{username})" if name else f"@{username}"
    return name or "без имени"


class TelegramWorker(QThread):
    """Поток общения с Telegram: вход, канал доставки, проверка ссылок.

    Все методы ниже зовутся из окна и сразу возвращают управление, ответ
    приходит сигналом — окно между делом остаётся живым. Клиент Telethon один
    на весь сеанс: вход состоит из нескольких обращений подряд, и все они
    должны идти через одно соединение.
    """

    status = Signal(str)              # что происходит прямо сейчас
    code_requested = Signal()         # код отправлен, ждём ввода
    password_requested = Signal()     # включена двухфакторная защита
    logged_in = Signal(str)           # вход выполнен, имя человека
    logged_out = Signal()             # вышли
    failed = Signal(str)              # понятная человеку ошибка
    channel_created = Signal(str)     # создан канал доставки, его название
    # проверка ссылки: (ссылка, итог, пояснение). Итог: ok | renamed | fail.
    # При renamed пояснение — новая ссылка, при fail — причина.
    channel_checked = Signal(str, str, str)

    def __init__(self, client_factory=None, parent=None):
        super().__init__(parent)
        self._client_factory = client_factory or default_client_factory
        self._client = None
        self._phone = ""
        self._code_hash = ""
        self._loop = None
        self._ready = threading.Event()

    # ---------- жизнь потока ----------

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def shutdown(self, timeout_ms=5000):
        """Закрыть соединение и остановить поток. Зовётся при закрытии окна."""
        if self._loop is None or not self.isRunning():
            return
        done = threading.Event()

        async def close():
            try:
                if self._client is not None and self._client.is_connected():
                    await self._client.disconnect()
            except Exception as e:
                logger.warning(f"   [!] Telegram: не закрылось соединение: {e}")
            finally:
                done.set()
                self._loop.call_soon_threadsafe(self._loop.stop)

        asyncio.run_coroutine_threadsafe(close(), self._loop)
        done.wait(timeout_ms / 1000)
        self.wait(timeout_ms)

    def release_session(self, timeout_ms=8000):
        """Отпустить файл сессии, не останавливая поток.

        Файл сессии один на программу, и это база SQLite: пока её держит окно,
        прогон получает «database is locked» и не стартует вовсе. Поэтому перед
        прогоном соединение закрывается, а после — восстанавливается первым же
        обращением (check и остальные методы поднимают клиент заново).
        """
        if self._loop is None or not self.isRunning():
            return
        done = threading.Event()

        async def close():
            try:
                if self._client is not None and self._client.is_connected():
                    await self._client.disconnect()
            except Exception as e:
                logger.warning(f"   [!] Telegram: сессия не отпустилась: {e}")
            finally:
                self._client = None
                done.set()

        asyncio.run_coroutine_threadsafe(close(), self._loop)
        done.wait(timeout_ms / 1000)

    def _run_async(self, make_coro):
        """Отправить корутину в поток. Любая ошибка становится сигналом failed."""
        if not self._ready.wait(5) or self._loop is None:
            self.failed.emit("Не удалось запустить фоновый поток.")
            return

        async def guarded():
            try:
                await make_coro()
            except Exception as e:
                self.failed.emit(human_error(e))

        asyncio.run_coroutine_threadsafe(guarded(), self._loop)

    async def _connected_client(self):
        if self._client is None:
            self._client = self._client_factory()
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    # ---------- то, что зовёт окно ----------

    def check(self):
        """Проверить, выполнен ли вход. Сети почти не требует."""
        self._run_async(self._check)

    def login(self, phone):
        self._run_async(lambda: self._login(phone))

    def submit_code(self, code):
        self._run_async(lambda: self._submit_code(code))

    def submit_password(self, password):
        self._run_async(lambda: self._submit_password(password))

    def logout(self):
        self._run_async(self._logout)

    def create_channel(self, title):
        self._run_async(lambda: self._create_channel(title))

    def check_channel(self, link):
        """Открывается ли канал по ссылке. Ничего не читает и не пересылает."""
        self._run_async(lambda: self._check_channel(link))

    # ---------- сами действия ----------

    async def _check(self):
        client = await self._connected_client()
        if await client.is_user_authorized():
            self.logged_in.emit(display_name(await client.get_me()))
        else:
            self.status.emit("Вход в Telegram не выполнен.")

    async def _login(self, phone):
        phone = str(phone).strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+") or not phone[1:].isdigit() or len(phone) < 8:
            self.failed.emit("Номер пишется с кодом страны и плюсом, например +79161234567.")
            return
        client = await self._connected_client()
        self.status.emit("Запрашиваю код у Telegram...")
        sent = await client.send_code_request(phone)
        self._phone = phone
        self._code_hash = getattr(sent, "phone_code_hash", "")
        self.code_requested.emit()

    async def _submit_code(self, code):
        code = str(code).strip()
        if not code:
            self.failed.emit("Введите код из сообщения Telegram.")
            return
        client = await self._connected_client()
        self.status.emit("Проверяю код...")
        try:
            me = await client.sign_in(self._phone, code, phone_code_hash=self._code_hash)
        except SessionPasswordNeededError:
            # у человека включена двухфакторная защита — это не ошибка
            self.password_requested.emit()
            return
        self.logged_in.emit(display_name(me))

    async def _submit_password(self, password):
        if not password:
            self.failed.emit("Введите пароль двухфакторной защиты.")
            return
        client = await self._connected_client()
        self.status.emit("Проверяю пароль...")
        me = await client.sign_in(password=password)
        self.logged_in.emit(display_name(me))

    async def _logout(self):
        client = await self._connected_client()
        self.status.emit("Выхожу из Telegram...")
        await client.log_out()
        self._client = None
        self._phone = ""
        self._code_hash = ""
        self.logged_out.emit()

    async def _check_channel(self, link):
        """Проверка ссылки тем же способом, что и в прогоне: сначала по ссылке,
        потом по запомненному id. Второй заход и ловит переименованные каналы.

        Ошибка здесь не сигнал failed, а результат проверки: не открылся один
        канал из полусотни — это не поломка окна.
        """
        client = await self._connected_client()
        # ошибку надо унести из блока except в обычную переменную: имя после
        # «except ... as» Python удаляет сразу по выходу из блока
        first_error = None
        try:
            await client.get_entity(link)
            self.channel_checked.emit(link, "ok", "")
            return
        except Exception as e:
            first_error = e

        cid = remembered_id(link)
        if not cid:
            # для только что добавленного канала id ещё не запомнен —
            # страховать нечем, и это нормально
            self.channel_checked.emit(link, "fail", str(first_error))
            return
        try:
            entity = await client.get_entity(PeerChannel(cid))
        except Exception as second_error:
            self.channel_checked.emit(
                link, "fail", f"{first_error}; по запомненному id тоже не открылся ({second_error})")
            return
        username = getattr(entity, "username", None)
        if username:
            self.channel_checked.emit(link, "renamed", "https://t.me/" + str(username))
        else:
            self.channel_checked.emit(link, "fail", f"{first_error}; канал стал приватным")

    async def _create_channel(self, title):
        """Создаёт приватный канал и записывает его в настройки как адрес доставки.

        Именно приватный канал, а не Избранное: в Избранном у человека свои
        сообщения, и сотня постов в день их похоронит.
        """
        title = str(title).strip() or "Дайджест"
        client = await self._connected_client()
        self.status.emit("Создаю канал для доставки...")
        result = await client(CreateChannelRequest(
            title=title, about=CHANNEL_ABOUT, megagroup=False))
        channel = result.chats[0]

        # у приватного канала нет ника, поэтому запоминаем числовой адрес
        data = settings.load(force=True)
        data["telegram"]["target"] = utils.get_peer_id(channel)
        settings.save(data)
        logger.info(f"Создан канал доставки: {title} ({data['telegram']['target']})")
        self.channel_created.emit(title)
