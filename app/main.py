# -*- coding: utf-8 -*-
"""HTTP-сервер програми. Інтерфейс відкривається у браузері, обробка йде тут.

Програма локальна: сервер слухає лише 127.0.0.1 і нікуди дані не відправляє,
крім запитів по супутникові знімки, якщо їх увімкнено.
"""

import json
import mimetypes
import os
import shutil
import socket
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.core.catalog import Картотека
from app.core.state import Журнал, Сеанс, безпечна_назва

БАЗА = ""
НАЛАШТУВАННЯ = {}
СЕАНС = None
КАРТОТЕКА = None
ВЕРСІЯ = "0.0.0"

МЕЖА_ТІЛА = 2 * 1024 ** 3  # 2 ГБ на один запит

# GDAL під Windows не любить, коли до нього лізуть із двох потоків одночасно:
# карта читає шар, поки задача пише свій. Один замок на все просторове читання
# коштує нам паузи в інтерфейсі під час обробки — і рятує від падіння процесу.
ЗАМОК_ПРОСТОРУ = threading.RLock()


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
            # заголовки їдуть у latin-1, тож кирилицю в імені файлу треба
            # закодувати — інакше відповідь рветься просто посеред шапки
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''" + quote(назва_для_завантаження, safe=""),
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
        # кирилиця в адресі приїжджає закодованою — без цього стиль і скрипт не знайдуться
        шлях = unquote(адреса.path)
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
            if шлях == "/підкладка":
                г, п = запит.get("господарство"), запит.get("поле")
                return self._файл_з_диска(
                    os.path.join(КАРТОТЕКА.тека_поля(г, п), "шари", "підкладка.png"))
            return self._збій("Немає такої сторінки", 404)
        except Exception as помилка:
            traceback.print_exc()
            return self._збій(str(помилка), 500)

    def do_POST(self):
        адреса = urlparse(self.path)
        шлях = unquote(адреса.path)
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
        if дія == "картотека":
            return self._віддати({"господарства": КАРТОТЕКА.господарства()})
        if дія == "поле":
            г, п = запит.get("господарство"), запит.get("поле")
            return self._віддати({
                "паспорт": КАРТОТЕКА.паспорт_поля(г, п),
                "шари": КАРТОТЕКА.шари(г, п),
            })
        if дія == "шар":
            return self._шар(запит)
        return self._збій("Невідомий запит: " + дія, 404)

    def _шар(self, запит):
        from app.core import render

        г, п, ключ = запит.get("господарство"), запит.get("поле"), запит.get("ключ")
        шар = КАРТОТЕКА.шар(г, п, ключ)
        if not шар:
            return self._збій("Такого шару немає", 404)
        атрибут = запит.get("атрибут") or шар.get("атрибут")
        with ЗАМОК_ПРОСТОРУ:
            дані = render.шар_для_карти(шар["_шлях"], атрибут, тип=шар.get("тип"))
        класів = int(запит.get("класів") or 6)
        метод = запит.get("метод") or "квантилі"
        значення = дані.get("значення")
        if значення:
            дані["межі_класів"] = render.класифікувати(
                [з for з in значення if з is not None], класів, метод)
            дані["кольори"] = render.палітра(
                render.ПІД_ТИП.get(шар.get("тип"), "нейтральна"),
                max(len(дані["межі_класів"]) - 1, 1))
        дані["шар"] = {к: в for к, в in шар.items() if not к.startswith("_")}
        return self._віддати(дані)

    # --- POST api ---

    def _api_post(self, дія, дані, файли):
        global СЕАНС
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
        if дія == "обрати":
            г, п = (дані or {}).get("господарство"), (дані or {}).get("поле")
            if СЕАНС.працює():
                return self._збій("Зачекайте, задача ще виконується")
            СЕАНС.тека = КАРТОТЕКА.тека_поля(г, п)
            СЕАНС.паспорт = {"поле": КАРТОТЕКА.паспорт_поля(г, п).get("назва")}
            СЕАНС.розвідка = None
            return self._віддати({"гаразд": True, "тека": СЕАНС.тека})
        if дія == "очистити-вхід":
            вид = (дані or {}).get("вид") or "монітор"
            тека = СЕАНС.шлях("1_вхідні_дані", вид) if СЕАНС.тека else None
            if тека and os.path.isdir(тека):
                import shutil

                shutil.rmtree(тека, ignore_errors=True)
            return self._віддати({"гаразд": True})
        if дія == "господарство":
            ключ = КАРТОТЕКА.завести_господарство((дані or {}).get("назва") or "")
            return self._віддати({"гаразд": True, "ключ": ключ})
        if дія == "нове-поле":
            г = (дані or {}).get("господарство")
            ключ = КАРТОТЕКА.завести_поле(г, (дані or {}).get("назва") or "")
            return self._віддати({"гаразд": True, "ключ": ключ})
        if дія == "контур":
            return self._контур(дані, файли)
        if дія == "шар-файл":
            return self._шар_файл(дані, файли)
        if дія == "підкладка":
            return self._підкладка(дані)
        if дія == "задача":
            return self._задача(дані)
        if дія == "скинути":
            СЕАНС = Сеанс(БАЗА, НАЛАШТУВАННЯ)
            return self._віддати({"гаразд": True})
        return self._збій("Невідома дія: " + дія, 404)

    def _паспорт(self, дані):
        СЕАНС.паспорт.update(дані or {})
        # якщо сеанс уже привʼязаний до поля картотеки — теку не вигадуємо
        if not СЕАНС.тека and СЕАНС.паспорт.get("поле") and СЕАНС.паспорт.get("рік"):
            СЕАНС.завести_теку()
        if СЕАНС.тека:
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

    def _контур(self, поля, файли):
        """Контур кладеться в поле один раз і далі береться звідти."""
        from app.core import reading

        г, п = поля.get("господарство"), поля.get("поле")
        if not г or not п:
            return self._збій("Не вказано поле")
        тека = os.path.join(КАРТОТЕКА.тека_поля(г, п), "1_вхідні_дані", "контур")
        os.makedirs(тека, exist_ok=True)
        for ф in файли:
            with open(os.path.join(тека, безпечна_назва(ф["імʼя"], "файл")), "wb") as вихід:
                вихід.write(ф["дані"])

        тимчасовий = Сеанс(БАЗА, НАЛАШТУВАННЯ)
        тимчасовий.тека = КАРТОТЕКА.тека_поля(г, п)
        with ЗАМОК_ПРОСТОРУ:
            контур, опис = reading.прочитати_контур(тимчасовий)
            площа = КАРТОТЕКА.покласти_контур(г, п, контур)
        return self._віддати({"гаразд": True, "площа_га": round(площа, 2), "опис": опис})

    def _шар_файл(self, поля, файли):
        """Будь-який точковий шар у поле: сканування, EC, агрохімія."""
        from app.core import reading

        г, п = поля.get("господарство"), поля.get("поле")
        якщо_тип = поля.get("тип") or "сканування"
        if not г or not п:
            return self._збій("Не вказано поле")
        if not файли:
            return self._збій("Файлів немає")

        тимчасова = os.path.join(КАРТОТЕКА.тека_поля(г, п), "1_вхідні_дані", "прийом")
        shutil.rmtree(тимчасова, ignore_errors=True)
        os.makedirs(тимчасова, exist_ok=True)
        for ф in файли:
            with open(os.path.join(тимчасова, безпечна_назва(ф["імʼя"], "файл")), "wb") as вихід:
                вихід.write(ф["дані"])

        with ЗАМОК_ПРОСТОРУ:
            import geopandas as gpd

            контур = КАРТОТЕКА.контур(г, п)
            if контур is None:
                return self._збій("Спершу потрібен контур поля")
            знайдені = reading.знайти_шари(тимчасова)
            шар = None
            for шлях in знайдені:
                try:
                    прочитане = reading.прочитати_шар(шлях)
                except Exception:
                    continue
                точки = прочитане[прочитане.geometry.geom_type == "Point"]
                if len(точки):
                    шар = точки
                    break
            if шар is None:
                return self._збій("У наданих файлах немає точок")
            if шар.crs is None:
                шар = шар.set_crs(4326)
            шар = шар.to_crs(контур.crs)

            ключ = безпечна_назва(поля.get("ключ") or якщо_тип, якщо_тип)
            файл = "{}.gpkg".format(ключ)
            тека_шарів = os.path.join(КАРТОТЕКА.тека_поля(г, п), "шари")
            os.makedirs(тека_шарів, exist_ok=True)
            шар.to_file(os.path.join(тека_шарів, файл), driver="GPKG", layer=ключ)

            числові = [к for к in шар.columns
                       if к != "geometry" and шар[к].dtype.kind in "if"]
            КАРТОТЕКА.додати_шар(
                г, п, ключ, поля.get("назва") or якщо_тип, якщо_тип, файл,
                рік=int(поля.get("рік") or 0) or None,
                атрибут=(числові[0] if числові else None),
                походження=поля.get("походження") or "завантажений файл",
                колонки=числові,
            )
        return self._віддати({"гаразд": True, "ключ": ключ, "точок": int(len(шар)),
                              "колонки": числові})

    def _підкладка(self, дані):
        from app.core import render

        г, п = дані.get("господарство"), дані.get("поле")
        контур = КАРТОТЕКА.контур(г, п)
        if контур is None:
            return self._збій("Спершу потрібен контур поля")
        тека = os.path.join(КАРТОТЕКА.тека_поля(г, п), "шари")
        with ЗАМОК_ПРОСТОРУ:
            звіт = render.підкладка_знімком(контур, дані, НАЛАШТУВАННЯ, тека)
        if not звіт:
            return self._віддати({"гаразд": False,
                                  "повідомлення": "Чистого знімка для підкладки не знайшлось"})
        звіт["гаразд"] = True
        return self._віддати(звіт)

    def _задача(self, дані):
        from app.core import tasks

        if СЕАНС.працює():
            return self._збій("Одна задача вже виконується")
        г, п = дані.get("господарство"), дані.get("поле")
        режим = дані.get("режим") or "нормалізація"
        if not г or not п:
            return self._збій("Не вказано, над яким полем працюємо")

        СЕАНС.паспорт.update(дані.get("паспорт") or {})
        СЕАНС.паспорт.setdefault("поле", КАРТОТЕКА.паспорт_поля(г, п).get("назва"))
        СЕАНС.тека = КАРТОТЕКА.тека_поля(г, п)
        СЕАНС.записати_паспорт()
        СЕАНС.журнал = Журнал()

        if режим == "нормалізація":
            СЕАНС.підсумок = None
            ціль, аргументи = tasks.нормалізація, (СЕАНС, КАРТОТЕКА, г, п)
        elif режим == "зони":
            завдання = self._зібрати_зонування(дані, г, п)
            ціль, аргументи = tasks.зонування, (СЕАНС, КАРТОТЕКА, г, п, завдання)
        else:
            return self._збій("Режим «{}» ще не зроблений".format(режим))

        def під_замком():
            with ЗАМОК_ПРОСТОРУ:
                ціль(*аргументи)

        СЕАНС.потік = threading.Thread(target=під_замком, daemon=True)
        СЕАНС.потік.start()
        return self._віддати({"гаразд": True})

    def _зібрати_зонування(self, дані, г, п):
        """Джерела приходять від користувача; шляхи до шарів підставляємо тут."""
        джерела = []
        for джерело in (дані.get("джерела") or []):
            джерело = dict(джерело)
            if джерело.get("вид") == "шар":
                шар = КАРТОТЕКА.шар(г, п, джерело.get("ключ"))
                if not шар:
                    raise ValueError("Шару «{}» у цьому полі немає".format(джерело.get("ключ")))
                джерело["_шлях"] = шар["_шлях"]
                джерело.setdefault("назва", шар.get("назва"))
                джерело.setdefault("атрибут", шар.get("атрибут"))
            джерела.append(джерело)
        return {
            "джерела": джерела,
            "зони": дані.get("зони") or {},
            "ключ": дані.get("ключ") or "зони",
            "назва": дані.get("назва") or "Зони",
            "атрибут_показу": дані.get("атрибут_показу"),
        }

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
    global БАЗА, НАЛАШТУВАННЯ, СЕАНС, КАРТОТЕКА, ВЕРСІЯ
    БАЗА = база
    НАЛАШТУВАННЯ = прочитати_json(os.path.join(база, "налаштування.json"))
    ВЕРСІЯ = прочитати_json(os.path.join(база, "version.json")).get("version", "0.0.0")
    СЕАНС = Сеанс(база, НАЛАШТУВАННЯ)
    корінь = НАЛАШТУВАННЯ.get("тека_результатів") or "робота"
    if not os.path.isabs(корінь):
        корінь = os.path.join(база, корінь)
    КАРТОТЕКА = Картотека(корінь)

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
