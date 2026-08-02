import requests
import time
from . import config, settings
from .logs import logger


def endpoint():
    """Адрес и имя модели: сначала настройки, потом значения из config.

    config остаётся запасным вариантом не для красоты: settings.load() бросает
    исключение, если settings.json нет, а topic_finder настроек не читает и
    падать из-за них не должен.
    """
    try:
        return settings.get("model.url", config.LM_URL), settings.get("model.name", config.MODEL)
    except settings.SettingsError:
        return config.LM_URL, config.MODEL


def api_key():
    """Ключ доступа к модели или пустая строка.

    LM Studio ключа не требует, и пустое поле — норма: тогда заголовок
    авторизации не отправляется вовсе. Ключ нужен облачным адресам,
    совместимым с OpenAI.
    """
    try:
        return str(settings.get_secret("model.api_key") or "").strip()
    except settings.SettingsError:
        return ""


def probe(url=None, name=None, key=None, timeout=30):
    """Один короткий запрос к модели: жива ли она. Возвращает (успех, текст).

    Отдельно от chat() и с явными параметрами: окно проверяет то, что человек
    ВПИСАЛ в поля, а не то, что уже сохранено на диске. Иначе пришлось бы
    сохранять настройки до проверки, а это ровно наоборот.

    Текст ответа написан для человека и годится, чтобы показать его как есть.
    """
    # None означает «не передали, возьми из настроек», а пустая строка —
    # «человек стёр поле». Смешивать их нельзя: иначе проверка пустого адреса
    # молча уходила бы на сохранённый и отвечала «всё хорошо».
    saved_url, saved_name = endpoint()
    url = (saved_url if url is None else url).strip()
    name = (saved_name if name is None else name).strip()
    key = (api_key() if key is None else key).strip()
    if not url:
        return False, "Не указан адрес модели."
    if not name:
        return False, "Не указано имя модели."

    payload = {
        "model": name,
        "messages": [{"role": "user", "content": "Ответь одним словом: готово. /no_think"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    headers = {"Authorization": "Bearer " + key} if key else None
    try:
        r = requests.post(url, json=payload, timeout=timeout, headers=headers)
    except requests.exceptions.ConnectionError:
        return False, ("По этому адресу никто не отвечает. Запущен ли LM Studio "
                       "и включён ли в нём сервер?")
    except requests.exceptions.Timeout:
        return False, f"Модель не ответила за {timeout} секунд."
    except Exception as e:
        return False, f"Не получилось обратиться к модели: {e}"

    if r.status_code in (401, 403):
        return False, "Адрес отвечает, но не принимает ключ доступа. Проверьте поле «Ключ»."
    if r.status_code == 404:
        return False, ("Адрес отвечает, но такой модели там нет. Проверьте имя модели "
                       "и то, что она загружена.")
    if not r.ok:
        return False, f"Модель ответила ошибкой {r.status_code}: {r.text[:200]}"
    try:
        message = r.json()["choices"][0]["message"]
        answer = (message.get("content") or message.get("reasoning_content") or "").strip()
    except Exception:
        return False, "Ответ пришёл, но разобрать его не удалось — это точно нужный адрес?"
    return True, f"Модель «{name}» ответила: {' '.join(answer.split())[:80] or '(пусто)'}"


class LLMUnavailable(RuntimeError):
    """Модель недоступна: связь/таймаут/сервер не ответил после всех попыток.

    Отдельный класс нужен, чтобы вызывающий код мог отличить «модель лежит»
    (надо прекращать весь прогон) от обычной ошибки на одном посте.
    """
    pass


def chat(prompt, temperature=0.3, max_tokens=4000, timeout=600, model=None,
         retries=3, raise_on_error=False):
    """Один запрос к локальной модели (LM Studio). Возвращает текст ответа.

    OpenAI-совместимый /v1/chat/completions.
    - retries: сколько раз повторить при ошибке связи/таймауте (с паузой).
    - raise_on_error: если True и все попытки провалились — БРОСАЕТ LLMUnavailable
      (для фильтра постов: ошибка != SKIP). Если False (по умолчанию) —
      возвращает "" (для некритичных вызовов вроде извлечения затравок).
    """
    url, default_model = endpoint()
    key = api_key()
    # без ключа заголовок не шлём совсем: LM Studio на пустой Bearer отвечает 401
    headers = {"Authorization": "Bearer " + key} if key else None
    payload = {
        "model": model or default_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout, headers=headers)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            content = msg.get("content")
            if not content:
                # reasoning-модели кладут текст в reasoning_content, а content шлют null.
                # Раньше отсюда возвращался None и вызывающий падал на .strip().
                content = msg.get("reasoning_content") or ""
            return content
        except Exception as e:
            last_err = e
            logger.warning(f"   [!] Ошибка обращения к модели (попытка {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(2 * attempt)   # нарастающая пауза: 2с, 4с
    if raise_on_error:
        raise LLMUnavailable(f"модель недоступна после {retries} попыток: {last_err}")
    return ""