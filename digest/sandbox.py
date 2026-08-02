"""Песочница для проверки входа в Telegram и создания канала доставки.

Зачем она нужна. Боевую сессию tg_digest.session трогать нельзя: выйдешь из
неё — и дайджест встанет, пока не войдёшь заново. Рабочий settings.json тоже
трогать нельзя: создание канала переписывает в нём адрес доставки.

Поэтому проверка идёт в отдельной папке ВНЕ проекта, со своим файлом сессии
(tg_test) и своими настройками. Из настоящих настроек берутся только api_id и
api_hash — без них Telegram не пустит. Боевые файлы не читаются на запись
и не изменяются.

    python digest/sandbox.py           запустить приложение в песочнице
    python digest/sandbox.py --clean   удалить песочницу целиком

ВАЖНО про то, чего песочница НЕ прячет: аккаунт Telegram у вас один. Вход в
песочнице — это настоящий вход, он появится в списке устройств Telegram.
Созданный канал — тоже настоящий, он появится в вашем списке чатов.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platformdirs import user_data_dir

from core import config, paths, settings

SANDBOX = os.path.join(user_data_dir("TelegramDigest-test", appauthor=False))
# своё имя хранилища секретов: настоящие учётные данные песочница не трогает
KEYRING_SERVICE = "TelegramDigest-test"
SESSION_NAME = "tg_test"
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")


def real_settings():
    """Читаем боевые настройки напрямую с диска, ничего не трогая."""
    path = os.path.join(config.PROJECT_ROOT, paths.SETTINGS_NAME)
    if not os.path.exists(path):
        raise SystemExit(f"[!] Не нашёл рабочие настройки: {path}")
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def prepare():
    """Готовит папку песочницы. Возвращает путь к ней."""
    if os.path.abspath(SANDBOX) == os.path.abspath(config.PROJECT_ROOT):
        raise SystemExit("[!] Песочница совпала с папкой проекта — так нельзя.")

    real = real_settings()
    template_path = os.path.join(config.PROJECT_ROOT, paths.SETTINGS_TEMPLATE_NAME)
    with open(template_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    # из личного берём только то, без чего Telegram не пустит. api_hash теперь
    # живёт в Диспетчере учётных данных, поэтому берём его оттуда, а в песочницу
    # кладём в файл: её собственное хранилище отдельное и пустое
    data["telegram"]["api_id"] = real["telegram"]["api_id"]
    data["telegram"]["api_hash"] = settings.get_secret("telegram.api_hash")
    data["telegram"]["session_name"] = SESSION_NAME     # своя сессия, не боевая
    data["telegram"]["target"] = ""                     # его и заполнит проверка
    data["bot"]["enabled"] = False                      # отчёты боту здесь не нужны

    os.makedirs(os.path.join(SANDBOX, "digest"), exist_ok=True)
    with open(os.path.join(SANDBOX, paths.SETTINGS_NAME), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    interests = os.path.join(SANDBOX, paths.INTERESTS_NAME)
    if not os.path.exists(interests):
        shutil.copyfile(os.path.join(config.PROJECT_ROOT, paths.INTERESTS_NAME), interests)
    return SANDBOX


def clean():
    if not os.path.exists(SANDBOX):
        print("Песочницы нет, удалять нечего.")
        return
    shutil.rmtree(SANDBOX, ignore_errors=True)
    print(f"Песочница удалена: {SANDBOX}")
    print("Напоминание: удаление файла сессии НЕ выходит из Telegram.")
    print("Если не нажимали «Выйти из Telegram», закройте этот вход вручную:")
    print("Telegram → Настройки → Устройства → найдите лишний сеанс и завершите его.")


def main():
    if "--clean" in sys.argv:
        clean()
        return 0

    home = prepare()
    print("=" * 70)
    print("ПЕСОЧНИЦА. Боевые файлы не участвуют.")
    print(f"  папка песочницы : {home}")
    print(f"  файл сессии     : {os.path.join(home, 'digest', SESSION_NAME + '.session')}")
    print(f"  боевая сессия   : {paths.session_path('tg_digest')}.session  (не тронута)")
    print("=" * 70)
    print("Что проверить в открывшемся окне:")
    print("  1. «Вход в Telegram…» → должна открыться страница НОМЕРА,")
    print("     а не «Вход выполнен»: сессия здесь пустая.")
    print("  2. Введите номер, потом код из приложения Telegram, потом пароль,")
    print("     если у вас включена двухфакторная защита.")
    print("  3. «Создать канал для доставки» → в вашем Telegram появится")
    print("     приватный канал «Дайджест». Это настоящий канал, удалите его потом сами.")
    print("  4. «Выйти из Telegram» → вернётся страница номера.")
    print()
    print("После проверки: python digest/sandbox.py --clean")
    print()

    env = dict(os.environ, DIGEST_HOME=home, DIGEST_KEYRING_SERVICE=KEYRING_SERVICE)
    return subprocess.call([sys.executable, APP], env=env)


if __name__ == "__main__":
    sys.exit(main())
