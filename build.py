# -*- coding: utf-8 -*-
"""Сборка программы одной командой:  python build.py

Делает два дела подряд, потому что порознь их легко перепутать местами
или забыть второе:

  1) собирает программу PyInstaller'ом;
  2) кладёт рядом с готовым .exe личный инструмент сео-поиска.

Второй шаг нужен потому, что PyInstaller перед сборкой сносит папку dist
целиком — вместе с положенным туда инструментом. Забыть об этом легко:
программа при этом не падает, просто раздел «Сео-поиск» молча исчезает
из настроек, и понять почему — отдельное расследование.

Если папки topic_finder рядом нет (так у всех, кроме автора), второй шаг
просто пропускается. Скрипт для этого и написан так, чтобы спокойно жить
в публичном репозитории.

Ключ --installer: собрать заодно и установщик Inno Setup.
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, "digest.spec")
APP_DIR = os.path.join(ROOT, "dist", "Парсер Telegram-каналов")
EXE = os.path.join(APP_DIR, "Парсер Telegram-каналов.exe")
TOPICS_SRC = os.path.join(ROOT, "topic_finder", "topic_finder.py")
TOPICS_DST_DIR = os.path.join(APP_DIR, "topic_finder")
ISS = os.path.join(ROOT, "installer.iss")
ISCC = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                    "Programs", "Inno Setup 6", "ISCC.exe")

# Что считаем исходниками: по ним сверяем, что сборка их новее.
SOURCE_DIRS = ("core", "digest")


def say(text=""):
    print(text, flush=True)


def running():
    """Запущена ли собираемая программа.

    PyInstaller не сможет переписать занятую папку dist и упадёт с ошибкой
    доступа. Сообщение у него невнятное, поэтому спрашиваем заранее.
    """
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             encoding="cp866", errors="replace").stdout
    except Exception:
        return False        # не смогли спросить — не мешаем собирать
    return "Telegram-" in out


def newest_source():
    """Время правки самого свежего исходника. По нему проверяем сборку."""
    newest, newest_path = 0, ""
    for folder in SOURCE_DIRS:
        for base, _, files in os.walk(os.path.join(ROOT, folder)):
            if "__pycache__" in base:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                stamp = os.path.getmtime(path)
                if stamp > newest:
                    newest, newest_path = stamp, path
    return newest, newest_path


def clock(stamp):
    return time.strftime("%H:%M:%S", time.localtime(stamp))


def build():
    say("[1/2] Собираю программу...")
    result = subprocess.run([sys.executable, "-m", "PyInstaller", SPEC, "--noconfirm"],
                            cwd=ROOT)
    if result.returncode != 0:
        say(f"      НЕ СОБРАЛОСЬ, код возврата {result.returncode}.")
        return False
    if not os.path.exists(EXE):
        say("      НЕ СОБРАЛОСЬ: готовой программы нет на месте.")
        return False
    say(f"      Готово: {clock(os.path.getmtime(EXE))}")
    return True


def place_topics():
    say("[2/2] Кладу сео-поиск рядом с программой...")
    if not os.path.exists(TOPICS_SRC):
        say("      Инструмента рядом нет — пропускаю. Это нормально:")
        say("      он есть только у автора и в сборку не входит.")
        return True
    shutil.rmtree(TOPICS_DST_DIR, ignore_errors=True)
    os.makedirs(TOPICS_DST_DIR)
    shutil.copy2(TOPICS_SRC, os.path.join(TOPICS_DST_DIR, "topic_finder.py"))
    # Данные (направления, история, кэш) не трогаем: они живут отдельно,
    # в папке пользователя, и пересборку переживают сами.
    say(f"      Положен: {os.path.getsize(TOPICS_SRC)} байт")
    return True


def check_fresh():
    """Сборка должна быть новее любого исходника.

    Именно этой проверки не хватало, когда правку в core/ забыли собрать:
    снаружи лежал новый код, внутри старое ядро, и программа падала
    на ровном месте.
    """
    stamp, path = newest_source()
    exe_stamp = os.path.getmtime(EXE)
    say()
    say(f"Самый свежий исходник: {clock(stamp)}  {os.path.relpath(path, ROOT)}")
    say(f"Собранная программа:   {clock(exe_stamp)}")
    if exe_stamp >= stamp:
        say("Сборка новее исходников — всё на месте.")
        return True
    say("ВНИМАНИЕ: сборка СТАРШЕ исходника. Внутри неё старый код.")
    return False


def build_installer():
    say()
    say("[+] Собираю установщик...")
    if not os.path.exists(ISCC):
        say(f"    Inno Setup не найден: {ISCC}")
        return False
    result = subprocess.run([ISCC, ISS], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        say(f"    НЕ СОБРАЛСЯ, код возврата {result.returncode}")
        say(result.stdout[-800:])
        return False
    # Личный инструмент в установщик попасть не должен: он исключён
    # в installer.iss, но проверить дешевле, чем однажды раздать его людям.
    if "topic_finder" in result.stdout:
        say("    ОПАСНО: в установщик попал сео-поиск! Проверьте installer.iss")
        return False
    # Inno Setup пишет путь к готовому файлу СЛЕДУЮЩЕЙ строкой после объявления.
    # Ловить всё, что кончается на .exe, нельзя: так в отчёт лезут сотни строк
    # «Compressing: ...».
    lines = result.stdout.splitlines()
    for i, line in enumerate(lines):
        if "Resulting Setup program" in line:
            path = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if path:
                say("    " + path)
                say(f"    {os.path.getsize(path)} байт")
            break
    say("    Сео-поиска в установщике нет — проверено.")
    return True


def main():
    if running():
        say("Программа сейчас запущена — закройте её окно.")
        say("PyInstaller не сможет переписать занятую папку dist.")
        return 1

    if not build():
        return 1
    if not place_topics():
        return 1
    fresh = check_fresh()

    if "--installer" in sys.argv:
        if not build_installer():
            return 1

    say()
    say("ГОТОВО." if fresh else "Готово, но посмотрите предупреждение выше.")
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
