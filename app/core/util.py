# -*- coding: utf-8 -*-
"""Дрібне спільне: системи координат, вгадування колонок, одиниці."""

import math
import re
import unicodedata


# ------------------------------------------------------------ координати


def метрична_crs(gdf):
    """Підбирає UTM-зону під центр геометрії. Рахувати в градусах не можна."""
    у_градусах = gdf.to_crs(4326)
    центр = у_градусах.geometry.union_all().centroid
    зона = int((центр.x + 180) // 6) + 1
    південна = центр.y < 0
    return 32700 + зона if південна else 32600 + зона


def площа_га(геометрія, crs):
    import geopandas as gpd

    ряд = gpd.GeoSeries([геометрія], crs=crs)
    if ряд.crs and ряд.crs.is_geographic:
        ряд = ряд.to_crs(метрична_crs(ряд.to_frame("geometry")))
    return float(ряд.area.iloc[0]) / 10000.0


# ------------------------------------------------------------ колонки


def _спростити(назва):
    текст = unicodedata.normalize("NFKD", str(назва)).lower()
    return re.sub(r"[^a-zа-яіїєґ0-9]+", "", текст)


# Порядок усередині списку — це порядок переваги.
ОЗНАКИ = {
    "врожай": [
        "yldmassdry", "yieldmassdry", "dryyield", "yldvoldry", "yieldvoldry",
        "yldmasswet", "yldvolwet", "wetyield", "yieldvolume", "yldvol", "yldmass",
        "vryieldvol", "vryieldmass", "yield", "врожайність", "врожай", "урожайность",
        "harvyield", "cropflow",
    ],
    "врожай_л": ["yldvoldry", "yldvolwet", "yieldvolume", "volumeperarea", "лга"],
    "вологість": [
        "moisture", "moist", "grainmoisture", "humidity", "volumemoisture",
        "вологість", "влажность", "moistpct",
    ],
    "висота": ["elevation", "elev", "altitude", "height", "gpselev", "висота", "высота", "z"],
    "ширина": [
        "swthwdth", "swathwidth", "swath", "cutwidth", "headerwidth", "hdrwidth",
        "width", "workingwidth", "ширина", "захват",
    ],
    "швидкість": ["speed", "gpsspeed", "velocity", "groundspeed", "швидкість", "скорость"],
    "час": [
        "datetime", "timestamp", "gpstime", "isotime", "time", "date", "час", "дата",
        "recordtime",
    ],
    "машина": [
        "machineid", "machine", "combine", "vehicleid", "vehicle", "harvester",
        "serialnumber", "serialnum", "objid", "equipment", "комбайн", "машина",
    ],
    "прохід": ["passnum", "pass", "swathnum", "tracknum", "track", "прохід", "проход"],
    "довжина": ["distance", "dist", "logdist", "sectiondist"],
    "потік": ["flow", "massflow", "grainflow", "wetmassflow"],
    "курс": ["heading", "track_deg", "course", "direction", "azimuth", "курс"],
}

# Колонки, які ніколи не є врожайністю, хоч і схожі
ЗАБОРОНЕНІ_ДЛЯ_ВРОЖАЮ = ("targetyield", "yieldtarget", "planyield", "prescription")


def вгадати_колонки(колонки):
    """{роль: назва колонки}. Що не впізнали — того просто немає."""
    спрощені = {к: _спростити(к) for к in колонки}
    знайдене = {}
    for роль, ознаки in ОЗНАКИ.items():
        for ознака in ознаки:
            for справжня, спрощена in спрощені.items():
                if справжня in знайдене.values():
                    continue
                if роль == "врожай" and any(з in спрощена for з in ЗАБОРОНЕНІ_ДЛЯ_ВРОЖАЮ):
                    continue
                if спрощена == ознака or ознака in спрощена:
                    знайдене[роль] = справжня
                    break
            if роль in знайдене:
                break
    # л/га має сенс лише окремо від головної врожайності
    if знайдене.get("врожай_л") == знайдене.get("врожай"):
        знайдене.pop("врожай_л", None)
    return знайдене


# ------------------------------------------------------------ одиниці

# У кг/га. Бушель залежить від культури — таблиця нижче.
БУШЕЛЬ_КГ = {
    "пшениця": 27.2155, "пшениця озима": 27.2155, "пшениця яра": 27.2155,
    "жито": 25.4012, "ячмінь": 21.7724, "ячмінь озимий": 21.7724, "ячмінь ярий": 21.7724,
    "овес": 14.5150, "кукурудза": 25.4012, "соя": 27.2155, "соняшник": 12.7006,
    "ріпак": 22.6796, "ріпак озимий": 22.6796, "горох": 27.2155, "сорго": 25.4012,
    "гречка": 21.7724,
}
АКР_У_ГА = 2.47105


def у_кг_на_га(значення, одиниця, культура=None):
    """Переводить масив/число в кг/га. Невідома одиниця → None."""
    одиниця = (одиниця or "").strip().lower()
    if одиниця in ("кг/га", "kg/ha", "kgha"):
        return значення
    if одиниця in ("т/га", "t/ha", "tha"):
        return значення * 1000.0
    if одиниця in ("ц/га", "c/ha", "cha"):
        return значення * 100.0
    if одиниця in ("bu/ac", "bushels/acre", "buac"):
        вага = БУШЕЛЬ_КГ.get((культура or "").strip().lower())
        if вага is None:
            return None
        return значення * вага * АКР_У_ГА
    if одиниця in ("lb/ac", "lbac"):
        return значення * 0.453592 * АКР_У_ГА
    return None


def підказати_одиницю(медіана, культура=None):
    """За порядком величини. Це здогад, який користувач може перебити."""
    if медіана is None or not math.isfinite(медіана) or медіана <= 0:
        return "", "Медіана незрозуміла — визначте одиницю вручну."
    if медіана > 1500:
        return "кг/га", "Медіана {:.0f} — це схоже на кілограми з гектара.".format(медіана)
    if 40 <= медіана <= 400:
        return "bu/ac", "Медіана {:.1f} — типовий діапазон бушелів з акра.".format(медіана)
    if 15 <= медіана < 40:
        return "ц/га", "Медіана {:.1f} — схоже на центнери з гектара.".format(медіана)
    if 1 <= медіана < 15:
        return "т/га", "Медіана {:.2f} — схоже на тонни з гектара.".format(медіана)
    return "", "Медіана {:.3f} ні на що звичне не схожа — вкажіть одиницю самі.".format(медіана)


def у_метри_ширина(значення):
    """Ширина жатки: якщо число більше 25 — це майже напевно фути або сантиметри."""
    import numpy as np

    масив = np.asarray(значення, dtype="float64")
    медіана = float(np.nanmedian(масив)) if масив.size else float("nan")
    if not math.isfinite(медіана) or медіана <= 0:
        return масив, "невідомо"
    if медіана > 200:
        return масив / 100.0, "сантиметри"
    if медіана > 25:
        return масив * 0.3048, "фути"
    return масив, "метри"
