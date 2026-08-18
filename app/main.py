# -*- coding: utf-8 -*-
"""HTTP-сервер програми. Інтерфейс відкривається у браузері, обробка йде тут.

Програма локальна: сервер слухає лише 127.0.0.1 і нікуди дані не відправляє,
крім запитів по супутникові знімки, якщо їх увімкнено.
"""

import json
import mimetypes
import os
import socket
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.core.state import Журнал, Сеанс, безпечна_назва

БАЗА = ""
НАЛАШТУВАННЯ = {}
СЕАНС = None
ВЕРСІЯ = "0.0.0"

МЕЖА_ТІЛА = 2 * 1024 ** 3  # 2 ГБ на один запит


# ---------------------------------------------------------------- допоміжне


def прочитати_json(шлях, замовчування=None):
    try:
        with open(шлях, encoding="utf-8") as ф:
            return json.load(ф)
    except Exception:
        return замовчування if замовчування is not None else {}


def розібрати_multipart(тіло, тип_вмісту):
    """Дуже простий розбір multipart/form-data. Повертає (поля, файли)."""
    поля, файли = {}, []
    межа = None
    for частина in тип_вмісту.split(";"):
        частина = частина.strip()
        if частина.startswith("boundary="):
            межа = частина[9:].strip('"')
    if not межа:
        return поля, файли

    роздільник = ("--" + межа).encode("utf-8")
    шматки = тіло.split(роздільник)
    for шматок in шматки:
        if not шматок or шматок in (b"--\r\n", b"--"):
            continue
        шматок = шматок.lstrip(b"\r\n")
        if шматок.startswith(b"--"):
            continue
        поділ = шматок.find(b"\r\n\r\n")
        if поділ < 0:
            continue
        заголовки = шматок[:поділ].decode("utf-8", "replace")
        вміст = шматок[поділ + 4:]
        if вміст.endswith(b"\r\n"):
            вміст = вміст[:-2]

        імʼя, файл = None, None
        for рядок in заголовки.split("\r\n"):
            if рядок.lower().startswith("content-disposition"):
                for шм in рядок.split(";"):
                    шм = шм.strip()
                    if шм.startswith("name="):
                        імʼя = шм[5:].strip('"')
                    elif шм.startswith("filename="):
                        файл = шм[9:].strip('"')
        if файл:
            файли.append({"поле": імʼя, "імʼя": os.path.basename(файл), "дані": вміст})
        elif імʼя:
            поля[імʼя] = вміст.decode("utf-8", "replace")
    return поля, файли


# ---------------------------------------------------------------- обробник


class Обробник(BaseHTTPRequestHandler):
    server_version = "FieldFactor"
    protocol_version = "HTTP/1.1"

    def log_message(self, формат, *арг):
        pass  # у консоль не сміттимо

    # --- відповіді ---

    def _віддати(self, дані, код=200, тип="application/json; charset=utf-8"):
        if isinstance(дані, (dict, list)):
            дані = json.dumps(дані, ensure_ascii=False).encode("utf-8")
        elif isinstance(дані, str):
            дані = дані.encode("utf-8")
        self.send_response(код)
        self.send_header("Content-Type", тип)
        self.send_header("Content-Length", str(len(дані)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(дані)

    def _збій(self, текст, код=400):
        self._віддати({"помилка": текст}, код)

    def _файл_з_диска(self, шлях, назва_для_завантаження=None):
        if not os.path.isfile(шлях):
            return self._збій("Файл не знайдено", 404)
        тип = mimetypes.guess_type(шлях)[0] or "application/octet-stream"
        розмір = os.path.getsize(шлях)
        self.send_response(200)
        self.send_header("Content-Type", тип)
        self.send_header("Content-Length", str(розмір))
        if назва_для_завантаження:
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''" + назва_для_завантаження.replace(" ", "%20"),
            )
        self.end_headers()
        with open(шлях, "rb") as ф:
            while True:
                шматок = ф.read(1 << 20)
                if not шматок:
                    break
                self.wfile.write(шматок)

    # --- маршрути ---

    def do_GET(self):
        адреса = urlparse(self.path)
        шлях = адреса.path
        запит = {к: в[0] for к, в in parse_qs(адреса.query).items()}
        try:
            if шлях in ("/", "/index.html"):
                return self._файл_з_диска(os.path.join(БАЗА, "app", "web", "index.html"))
            if шлях.startswith("/web/"):
                імʼя = os.path.basename(шлях)
                return self._файл_з_диска(os.path.join(БАЗА, "app", "web", імʼя))
            if шлях.startswith("/api/"):
                return self._api_get(шлях[5:], запит)
            if шлях == "/завантажити":
                return self._завантажити(запит)
            return self._збій("Немає такої сторінки", 404)
        except Exception as помилка:
            traceback.print_exc()
            return self._збій(str(помилка), 500)

    def do_POST(self):
        адреса = urlparse(self.path)
        шлях = адреса.path
        довжина = int(self.headers.get("Content-Length") or 0)
        if довжина > МЕЖА_ТІЛА:
            return self._збій("Файл завеликий", 413)
        тіло = self.rfile.read(довжина) if довжина else b""
        тип = self.headers.get("Content-Type") or ""
        try:
            if тип.startswith("multipart/form-data"):
                поля, файли = розібрати_multipart(тіло, тип)
                return self._api_post(шлях[5:], поля, файли)
            дані = json.loads(тіло.decode("utf-8")) if тіло else {}
            return self._api_post(шлях[5:], дані, [])
        except Exception as помилка:
            traceback.print_exc()
            return self._збій(str(помилка), 500)

    # --- GET api ---

    def _api_get(self, дія, запит):
        if дія == "стан":
            return self._віддати(
                {
                    "версія": ВЕРСІЯ,
                    "паспорт": СЕАНС.паспорт,
                    "тека": СЕАНС.тека,
                    "розвідка": СЕАНС.розвідка,
                    "працює": СЕАНС.працює(),
                    "підсумок": СЕАНС.підсумок,
                    "підсумок_зон": СЕАНС.підсумок_зон,
                    "замовчування": НАЛАШТУВАННЯ.get("замовчування", {}),
                }
            )
        if дія == "прогрес":
            від = int(запит.get("від") or 0)
            return self._віддати(СЕАНС.журнал.знімок(від))
        if дія == "оновлення":
            from app.core import update

            return self._віддати(update.перевірити(НАЛАШТУВАННЯ, ВЕРСІЯ))
        return self._збій("Невідомий запит: " + дія, 404)

    # --- POST api ---

    def _api_post(self, дія, дані, файли):
        if дія == "паспорт":
            return self._паспорт(дані)
        if дія == "файли":
            return self._файли(дані, файли)
        if дія == "розвідка":
            return self._розвідка()
        if дія == "прогін":
            return self._прогін()
        if дія == "зони":
            return self._зони(дані)
        if дія == "оновити":
            from app.core import update

            return self._віддати(update.поставити(БАЗА, НАЛАШТУВАННЯ, ВЕРСІЯ))
        if дія == "скинути":
            global СЕАНС
            СЕАНС = Сеанс(БАЗА, НАЛАШТУВАННЯ)
            return self._віддати({"гаразд": True})
        return self._збій("Невідома дія: " + дія, 404)

    def _паспорт(self, дані):
        СЕАНС.паспорт.update(дані or {})
        if СЕАНС.паспорт.get("поле") and СЕАНС.паспорт.get("рік"):
            СЕАНС.завести_теку()
            СЕАНС.записати_паспорт()
        return self._віддати({"гаразд": True, "тека": СЕАНС.тека})

    def _файли(self, поля, файли):
        if not СЕАНС.тека:
            return self._збій("Спершу назвіть поле і рік")
        вид = поля.get("вид") or "монітор"
        куди = СЕАНС.шлях("1_вхідні_дані", "контур" if вид == "контур" else "монітор")
        os.makedirs(куди, exist_ok=True)
        збережені = []
        for ф in файли:
            імʼя = безпечна_назва(ф["імʼя"], "файл")
            шлях = os.path.join(куди, імʼя)
            with open(шлях, "wb") as вихід:
                вихід.write(ф["дані"])
            збережені.append({"імʼя": імʼя, "байтів": len(ф["дані"])})
        return self._віддати({"гаразд": True, "збережено": збережені, "тека": куди})

    def _розвідка(self):
        from app.core import reading

        if not СЕАНС.тека:
            return self._збій("Спершу назвіть поле і рік")
        СЕАНС.розвідка = reading.розвідати(СЕАНС)
        return self._віддати(СЕАНС.розвідка)

    def _прогін(self):
        from app.core import pipeline

        if СЕАНС.працює():
            return self._збій("Прогін уже йде")
        СЕАНС.журнал = Журнал()
        СЕАНС.підсумок = None
        СЕАНС.потік = threading.Thread(
            target=pipeline.виконати, args=(СЕАНС,), daemon=True
        )
        СЕАНС.потік.start()
        return self._віддати({"гаразд": True})

    def _зони(self, дані):
        from app.core import zones

        if СЕАНС.працює():
            return self._збій("Прогін уже йде")
        if not СЕАНС.підсумок:
            return self._збій("Спершу треба зробити нормалізовану карту")
        СЕАНС.журнал = Журнал()
        СЕАНС.потік = threading.Thread(
            target=zones.виконати, args=(СЕАНС, дані or {}), daemon=True
        )
        СЕАНС.потік.start()
        return self._віддати({"гаразд": True})

    def _завантажити(self, запит):
        імʼя = os.path.basename(запит.get("файл") or "")
        if not імʼя or not СЕАНС.тека:
            return self._збій("Нема чого завантажувати", 404)
        шлях = СЕАНС.шлях("3_віддача", імʼя)
        return self._файл_з_диска(шлях, імʼя)


# ---------------------------------------------------------------- запуск


def вільний_порт(бажаний):
    for порт in range(бажаний, бажаний + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as с:
            if с.connect_ex(("127.0.0.1", порт)) != 0:
                return порт
    return бажаний


def запустити(база):
    global БАЗА, НАЛАШТУВАННЯ, СЕАНС, ВЕРСІЯ
    БАЗА = база
    НАЛАШТУВАННЯ = прочитати_json(os.path.join(база, "налаштування.json"))
    ВЕРСІЯ = прочитати_json(os.path.join(база, "version.json")).get("version", "0.0.0")
    СЕАНС = Сеанс(база, НАЛАШТУВАННЯ)

    порт = вільний_порт(int(НАЛАШТУВАННЯ.get("порт") or 8756))
    адреса = "http://127.0.0.1:{}/".format(порт)

    сервер = ThreadingHTTPServer(("127.0.0.1", порт), Обробник)
    сервер.daemon_threads = True

    print("")
    print("  FieldFactor {}".format(ВЕРСІЯ))
    print("  " + "-" * 40)
    print("  Програма працює. Відкрито у браузері:")
    print("  " + адреса)
    print("")
    print("  Це вікно закривати не можна — воно і є програма.")
    print("  Щоб завершити роботу, закрийте його або натисніть Ctrl+C.")
    print("")

    if НАЛАШТУВАННЯ.get("відкривати_браузер", True):
        threading.Timer(0.8, lambda: webbrowser.open(адреса)).start()

    try:
        сервер.serve_forever()
    except KeyboardInterrupt:
        print("\n  Роботу завершено.")
    finally:
        сервер.server_close()
        return 0
