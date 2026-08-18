# -*- coding: utf-8 -*-
"""Стан сеансу: паспорт замовлення, тека проєкту, журнал прогону.

Програма розрахована на одного користувача за раз. Стан живе в памʼяті
і дублюється у `паспорт.json` теки проєкту, щоб прогін можна було повторити.
"""

import json
import os
import re
import threading
from datetime import datetime


def безпечна_назва(текст, замовчування="поле"):
    """Назва поля → назва теки. Кирилиця лишається, службові знаки — ні."""
    текст = (текст or "").strip()
    текст = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", текст)
    текст = re.sub(r"\s+", "_", текст).strip("._")
    return текст or замовчування


class Журнал:
    """Те, що користувач бачить у смужці прогресу. Потокобезпечний."""

    def __init__(self):
        self._замок = threading.Lock()
        self.рядки = []
        self.фаза = ""
        self.відсоток = 0
        self.завершено = False
        self.помилка = None

    def сказати(self, текст, відсоток=None, фаза=None):
        with self._замок:
            мітка = datetime.now().strftime("%H:%M:%S")
            self.рядки.append({"час": мітка, "текст": текст})
            if відсоток is not None:
                self.відсоток = int(відсоток)
            if фаза is not None:
                self.фаза = фаза

    def збій(self, текст):
        with self._замок:
            self.помилка = текст
            self.рядки.append(
                {"час": datetime.now().strftime("%H:%M:%S"), "текст": "ЗУПИНКА: " + текст}
            )
            self.завершено = True

    def кінець(self):
        with self._замок:
            self.відсоток = 100
            self.завершено = True

    def знімок(self, від=0):
        with self._замок:
            return {
                "рядки": self.рядки[від:],
                "усього_рядків": len(self.рядки),
                "фаза": self.фаза,
                "відсоток": self.відсоток,
                "завершено": self.завершено,
                "помилка": self.помилка,
            }


class Сеанс:
    """Один проєкт: поле, рік, файли, налаштування, результати."""

    def __init__(self, база, налаштування):
        self.база = база
        self.налаштування = налаштування
        self.паспорт = {}
        self.тека = None
        self.розвідка = None       # що знайшли у файлах (фаза 3)
        self.журнал = Журнал()
        self.підсумок = None       # результат прогону
        self.підсумок_зон = None
        self.потік = None

    # --- тека проєкту ---------------------------------------------------

    def завести_теку(self):
        корінь = self.налаштування.get("тека_результатів") or "робота"
        if not os.path.isabs(корінь):
            корінь = os.path.join(self.база, корінь)
        назва = "{}_{}".format(
            безпечна_назва(self.паспорт.get("поле")),
            self.паспорт.get("рік") or datetime.now().year,
        )
        self.тека = os.path.join(корінь, назва)
        for під in ("1_вхідні_дані", "2_проміжне", "3_віддача"):
            os.makedirs(os.path.join(self.тека, під), exist_ok=True)
        return self.тека

    def шлях(self, *частини):
        return os.path.join(self.тека, *частини)

    def записати_паспорт(self):
        if not self.тека:
            return
        дані = dict(self.паспорт)
        дані["_оновлено"] = datetime.now().isoformat(timespec="seconds")
        with open(self.шлях("паспорт.json"), "w", encoding="utf-8") as ф:
            json.dump(дані, ф, ensure_ascii=False, indent=2)

    def працює(self):
        return self.потік is not None and self.потік.is_alive()
