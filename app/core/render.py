# -*- coding: utf-8 -*-
"""Підготовка шарів до показу на карті і підкладка з реального знімка.

Малює не сервер, а браузер: сюди він дістає координати в метрах і значення
атрибута, а далі полотно робить решту. Так карта лишається живою — можна
крутити класифікацію й не чекати перемальовування на сервері.
"""

import os
import struct
import zlib

import numpy as np

МАКСИМУМ_ТОЧОК = 60000

ПАЛІТРИ = {
    "врожай": ["#8c3a22", "#c9743a", "#e6bf55", "#a8c95c", "#5d9f42", "#2f6b30"],
    "вегетація": ["#7a6a4f", "#a89a6a", "#cbd08a", "#9dc06a", "#5d9f42", "#255c2a"],
    "зони": ["#8c3a22", "#d08a3e", "#e8c85a", "#8fbf5a", "#3e7a32", "#1e4d2b"],
    "рельєф": ["#2f5d7a", "#5c8ba8", "#a8c0cc", "#cbbf9a", "#a8905c", "#7a6a4f"],
    "нейтральна": ["#e8eae5", "#c3ccbd", "#9aab93", "#71896b", "#4b6647", "#2c4429"],
}

ПІД_ТИП = {"врожайність": "врожай", "вегетація": "вегетація", "зони": "зони",
           "рельєф": "рельєф"}


# ------------------------------------------------------------ класифікація


def класифікувати(значення, класів=6, метод="квантилі"):
    """Межі класів. Метод обирає користувач, а не програма за нього."""
    числа = np.asarray(значення, dtype="float64")
    числа = числа[np.isfinite(числа)]
    if числа.size < 2:
        return []
    класів = int(max(2, min(12, класів)))

    if метод == "рівні":
        межі = np.linspace(числа.min(), числа.max(), класів + 1)
    elif метод == "розриви":
        from sklearn.cluster import KMeans

        зразок = числа if числа.size <= 20000 else np.random.RandomState(5).choice(
            числа, 20000, replace=False)
        модель = KMeans(n_clusters=класів, n_init=5, random_state=5).fit(зразок.reshape(-1, 1))
        центри = np.sort(модель.cluster_centers_.ravel())
        межі = np.concatenate([[числа.min()], (центри[:-1] + центри[1:]) / 2, [числа.max()]])
    else:
        межі = np.quantile(числа, np.linspace(0, 1, класів + 1))

    межі = np.unique(np.round(межі, 4))
    return [float(м) for м in межі]


def палітра(назва, класів):
    основа = ПАЛІТРИ.get(назва) or ПАЛІТРИ["нейтральна"]
    if класів <= len(основа):
        кроки = np.linspace(0, len(основа) - 1, класів).round().astype(int)
        return [основа[і] for і in кроки]
    # розтягуємо, домішуючи проміжні відтінки
    точки = np.linspace(0, len(основа) - 1, класів)
    кольори = []
    for т in точки:
        і = int(np.floor(т))
        ј = min(і + 1, len(основа) - 1)
        доля = т - і
        а = _у_числа(основа[і])
        б = _у_числа(основа[ј])
        кольори.append(_у_текст([round(а[к] + (б[к] - а[к]) * доля) for к in range(3)]))
    return кольори


def _у_числа(колір):
    колір = колір.lstrip("#")
    return [int(колір[і:і + 2], 16) for і in (0, 2, 4)]


def _у_текст(частини):
    return "#" + "".join("{:02x}".format(max(0, min(255, ч))) for ч in частини)


# ------------------------------------------------------------ шар на карту


def _прорідити(кількість, максимум):
    if кількість <= максимум:
        return None
    крок = int(np.ceil(кількість / максимум))
    return np.arange(0, кількість, крок)


def шар_для_карти(шлях, атрибут=None, максимум=МАКСИМУМ_ТОЧОК, тип=None):
    """Геометрія + значення атрибута у вигляді, який приймає полотно."""
    import geopandas as gpd
    import pandas as pd

    шари = gpd.list_layers(шлях)
    назва_шару = шари["name"].iloc[0] if len(шари) else None
    дані = gpd.read_file(шлях, layer=назва_шару)
    if дані.crs is None or _географічна(дані):
        дані = дані.to_crs(_метрична(дані))

    вид = дані.geometry.geom_type.iloc[0]
    відповідь = {
        "crs": int(дані.crs.to_epsg() or 0),
        "межі": [round(з, 2) for з in дані.total_bounds.tolist()],
        "атрибути": [к for к in дані.columns if к != "geometry"],
        "усього": int(len(дані)),
    }

    числові = [к for к in дані.columns
               if к != "geometry" and pd.api.types.is_numeric_dtype(дані[к])]
    відповідь["числові"] = числові
    if атрибут not in дані.columns:
        атрибут = атрибут if атрибут in числові else (числові[0] if числові else None)
    відповідь["атрибут"] = атрибут

    if вид in ("Polygon", "MultiPolygon"):
        відповідь["вид"] = "полігон"
        відповідь["фігури"] = _полігони(дані)
        if атрибут:
            відповідь["значення"] = _чисто(дані[атрибут])
        відповідь["підписи"] = [
            {к: _проста(дані[к].iloc[і]) for к in дані.columns if к != "geometry"}
            for і in range(len(дані))
        ]
        return відповідь

    відповідь["вид"] = "точки"
    вибір = _прорідити(len(дані), максимум)
    якщо = дані if вибір is None else дані.iloc[вибір]
    відповідь["показано"] = int(len(якщо))
    відповідь["проріджено"] = вибір is not None
    x = np.round(якщо.geometry.x.to_numpy(), 2)
    y = np.round(якщо.geometry.y.to_numpy(), 2)
    відповідь["коорд"] = np.column_stack([x, y]).ravel().tolist()
    if атрибут:
        відповідь["значення"] = _чисто(якщо[атрибут])
    for додатковий in ("SRC_TYPE", "CONF", "QC_FLAG"):
        if додатковий in якщо.columns:
            відповідь.setdefault("мітки", {})[додатковий] = [
                _проста(з) for з in якщо[додатковий].tolist()
            ]
    return відповідь


def _географічна(дані):
    try:
        return bool(дані.crs.is_geographic)
    except Exception:
        return False


def _метрична(дані):
    from app.core import util

    return util.метрична_crs(дані)


def _чисто(колонка):
    числа = np.asarray(колонка, dtype="float64")
    return [None if not np.isfinite(з) else round(float(з), 3) for з in числа]


def _проста(значення):
    if значення is None:
        return None
    if isinstance(значення, (np.integer, np.floating)):
        значення = значення.item()
    if isinstance(значення, float) and not np.isfinite(значення):
        return None
    return значення if isinstance(значення, (int, float, str)) else str(значення)


def _полігони(дані):
    фігури = []
    for геометрія in дані.geometry:
        частини = (list(геометрія.geoms) if геометрія.geom_type == "MultiPolygon"
                   else [геометрія])
        кільця = []
        for частина in частини:
            кільця.append([round(з, 2) for пара in частина.exterior.coords for з in пара])
            for дірка in частина.interiors:
                кільця.append([round(з, 2) for пара in дірка.coords for з in пара])
        фігури.append(кільця)
    return фігури


# ------------------------------------------------------------ підкладка


def записати_png(шлях, rgb):
    """Мінімальний писар PNG: не тягнемо заради цього ще одну бібліотеку."""
    висота, ширина, _ = rgb.shape
    рядки = bytearray()
    for р in range(висота):
        рядки.append(0)                       # фільтр «без фільтра»
        рядки.extend(rgb[р].tobytes())

    def шматок(тип, дані):
        return (struct.pack(">I", len(дані)) + тип + дані
                + struct.pack(">I", zlib.crc32(тип + дані) & 0xFFFFFFFF))

    with open(шлях, "wb") as ф:
        ф.write(b"\x89PNG\r\n\x1a\n")
        ф.write(шматок(b"IHDR", struct.pack(">IIBBBBB", ширина, висота, 8, 2, 0, 0, 0)))
        ф.write(шматок(b"IDAT", zlib.compress(bytes(рядки), 6)))
        ф.write(шматок(b"IEND", b""))
    return шлях


def підкладка_знімком(контур, паспорт, налаштування, тека_виводу, журнал=None):
    """Справжній знімок поля як тло карти. Не вийшло — не біда, повертаємо None."""
    from app.core import satellite

    try:
        import planetary_computer
        from pystac_client import Client
        import rasterio
        from rasterio.warp import Resampling, reproject
    except Exception:
        return None

    рік = int(паспорт.get("рік") or 0) or None
    вікна = satellite.вікна_сезону(паспорт.get("культура"), рік) if рік else []
    if not вікна:
        return None
    назва, початок, кінець = вікна[len(вікна) // 2]      # середина сезону

    сітка = satellite.сітка_поля(контур, крок=10.0)
    межі_град = tuple(контур.to_crs(4326).total_bounds)

    try:
        клієнт = Client.open(satellite.КАТАЛОГ, modifier=planetary_computer.sign_inplace)
        пошук = клієнт.search(
            collections=[satellite.КОЛЕКЦІЯ], bbox=межі_град,
            datetime="{}/{}".format(початок.isoformat(), кінець.isoformat()),
            query={"eo:cloud_cover": {"lt": 20}},
        )
        записи = sorted(пошук.items(), key=lambda з: з.properties.get("eo:cloud_cover", 100))
    except Exception:
        return None
    if not записи:
        return None

    запис = записи[0]
    смуги = []
    try:
        for назва_смуги in ("red", "green", "blue"):
            актив = запис.assets.get(назва_смуги)
            if актив is None:
                return None
            ціль = np.full((сітка["висота"], сітка["ширина"]), np.nan, dtype="float32")
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open(актив.href) as джерело:
                    reproject(source=rasterio.band(джерело, 1), destination=ціль,
                              src_transform=джерело.transform, src_crs=джерело.crs,
                              dst_transform=сітка["перетворення"], dst_crs=сітка["crs"],
                              resampling=Resampling.bilinear, dst_nodata=np.nan)
            смуги.append(ціль)
    except Exception:
        return None

    rgb = np.zeros((сітка["висота"], сітка["ширина"], 3), dtype="uint8")
    for і, смуга in enumerate(смуги):
        добрі = np.isfinite(смуга) & (смуга > 0)
        if добрі.sum() < 10:
            return None
        низ, верх = np.percentile(смуга[добрі], [2, 98])
        розтяг = np.clip((смуга - низ) / max(верх - низ, 1e-6), 0, 1)
        rgb[:, :, і] = np.where(добрі, розтяг * 255, 0).astype("uint8")

    os.makedirs(тека_виводу, exist_ok=True)
    шлях = os.path.join(тека_виводу, "підкладка.png")
    записати_png(шлях, rgb)
    xmin, ymin, xmax, ymax = сітка["межі"]
    if журнал:
        журнал.сказати("Підкладка: знімок {} ({})".format(запис.datetime.date(), назва))
    return {"файл": os.path.basename(шлях),
            "межі": [xmin, ymin, xmax, ymax],
            "дата": str(запис.datetime.date()),
            "вікно": назва}
