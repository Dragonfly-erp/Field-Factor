# -*- coding: utf-8 -*-
"""Оновлення програми.

Програма ходить на GitHub за новою версією, забирає тільки код (кілька МБ)
і кладе його поверх старого. Вбудований Python, тека `робота` і файл
`налаштування.json` не чіпаються ніколи.
"""

import io
import json
import os
import shutil
import zipfile
from urllib.request import Request, urlopen

# Що перезаписується при оновленні. Решта лишається як є.
ОНОВЛЮВАНЕ = ("app", "setup", "start.py", "version.json", "ЗАПУСК.bat", "ВСТАНОВИТИ.bat")


def _число(версія):
    частини = []
    for шматок in str(версія).lstrip("vV").split("."):
        цифри = "".join(с for с in шматок if с.isdigit())
        частини.append(int(цифри) if цифри else 0)
    while len(частини) < 3:
        частини.append(0)
    return tuple(частини[:3])


def _запит(адреса, як_текст=True, таймаут=15):
    запит = Request(адреса, headers={"User-Agent": "FieldFactor", "Accept": "application/vnd.github+json"})
    with urlopen(запит, timeout=таймаут) as відповідь:
        дані = відповідь.read()
    return дані.decode("utf-8") if як_текст else дані


def перевірити(налаштування, поточна):
    """Чи є новіша версія. Мережевий збій — не помилка, просто мовчимо."""
    репо = (налаштування.get("оновлення") or {}).get("репозиторій") or ""
    репо = репо.strip().strip("/")
    if not репо or "/" not in репо:
        return {
            "доступно": False,
            "причина": "Канал оновлень не налаштований. Впишіть репозиторій "
                       "у файл налаштування.json, рядок «репозиторій».",
            "поточна": поточна,
        }
    try:
        сирець = _запит("https://api.github.com/repos/{}/releases/latest".format(репо))
        реліз = json.loads(сирець)
    except Exception as помилка:
        return {"доступно": False, "причина": "Не вдалось звʼязатися: {}".format(помилка),
                "поточна": поточна}

    нова = (реліз.get("tag_name") or "").lstrip("vV")
    if not нова or _число(нова) <= _число(поточна):
        return {"доступно": False, "причина": "У вас найновіша версія.", "поточна": поточна}

    return {
        "доступно": True,
        "поточна": поточна,
        "нова": нова,
        "що_нового": (реліз.get("body") or "").strip()[:2000],
        "адреса": реліз.get("zipball_url"),
    }


def поставити(база, налаштування, поточна):
    """Забрати нову версію і покласти поверх. Стару зберігаємо у _попередня."""
    звіт = перевірити(налаштування, поточна)
    if not звіт.get("доступно"):
        return {"гаразд": False, "повідомлення": звіт.get("причина", "Оновлень немає")}

    try:
        архів = _запит(звіт["адреса"], як_текст=False, таймаут=120)
    except Exception as помилка:
        return {"гаразд": False, "повідомлення": "Не вдалось завантажити: {}".format(помилка)}

    тимчасова = os.path.join(база, "_оновлення")
    shutil.rmtree(тимчасова, ignore_errors=True)
    os.makedirs(тимчасова, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(архів)) as зіп:
            зіп.extractall(тимчасова)
    except Exception as помилка:
        shutil.rmtree(тимчасова, ignore_errors=True)
        return {"гаразд": False, "повідомлення": "Архів пошкоджений: {}".format(помилка)}

    # GitHub загортає все в одну теку — знаходимо її
    вміст = [os.path.join(тимчасова, і) for і in os.listdir(тимчасова)]
    корінь = вміст[0] if len(вміст) == 1 and os.path.isdir(вміст[0]) else тимчасова

    резерв = os.path.join(база, "_попередня_версія")
    shutil.rmtree(резерв, ignore_errors=True)
    os.makedirs(резерв, exist_ok=True)

    поставлено = []
    for імʼя in ОНОВЛЮВАНЕ:
        нове = os.path.join(корінь, імʼя)
        старе = os.path.join(база, імʼя)
        if not os.path.exists(нове):
            continue
        if os.path.exists(старе):
            shutil.move(старе, os.path.join(резерв, імʼя))
        shutil.move(нове, старе)
        поставлено.append(імʼя)

    shutil.rmtree(тимчасова, ignore_errors=True)
    _долити_налаштування(база, корінь)

    return {
        "гаразд": True,
        "нова": звіт.get("нова"),
        "оновлено": поставлено,
        "повідомлення": "Версію {} встановлено. Закрийте програму і запустіть ЗАПУСК.bat "
                        "ще раз.".format(звіт.get("нова")),
    }


def _долити_налаштування(база, корінь):
    """Нові ключі з нової версії додаємо, ваші значення лишаємо недоторканими."""
    новий = os.path.join(корінь, "налаштування.json")
    свій = os.path.join(база, "налаштування.json")
    if not os.path.isfile(новий) or not os.path.isfile(свій):
        return
    try:
        with open(новий, encoding="utf-8") as ф:
            з_нової = json.load(ф)
        with open(свій, encoding="utf-8") as ф:
            моє = json.load(ф)
    except Exception:
        return

    def долити(джерело, ціль):
        for ключ, значення in джерело.items():
            if ключ not in ціль:
                ціль[ключ] = значення
            elif isinstance(значення, dict) and isinstance(ціль.get(ключ), dict):
                долити(значення, ціль[ключ])

    долити(з_нової, моє)
    with open(свій, "w", encoding="utf-8") as ф:
        json.dump(моє, ф, ensure_ascii=False, indent=2)
