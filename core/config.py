# ====== ОБЩИЕ СЕКРЕТЫ И НАСТРОЙКИ ДЛЯ ОБОИХ АГЕНТОВ ======
# Единственное место, где лежат токен бота, chat_id и параметры модели.
# Меняешь здесь — меняется сразу и в digest, и в topic_finder.
import os

# --- Локальная модель (LM Studio, OpenAI-совместимый endpoint) ---
LM_URL = os.environ.get("LM_URL", "http://localhost:1234/v1/chat/completions")
MODEL = os.environ.get("LM_MODEL", "qwen3-8b-128k")

# --- Telegram-бот, куда шлём результаты (@BotFather / @userinfobot) ---
# Здесь ПУСТО, и так и должно быть: настоящий токен живёт в settings.json,
# который не попадает ни в репозиторий, ни в дистрибутив. Эти два значения —
# только запасной вариант и точка для переопределения окружением.
# Кто их читает и в каком порядке — см. core/telegram.py, функция credentials().
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
CHAT_ID = int(os.environ.get("TG_CHAT_ID") or 0)

# --- Пути к общим данным (файлы, которыми делятся агенты) ---
# Корень проекта = папка над core/ (там же лежат digest/ и topic_finder/).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# «Мостик» синергии: свежие затравки из интересных постов digest -> topic_finder.
FRESH_SEEDS_FILE = os.path.join(PROJECT_ROOT, "fresh_seeds.json")