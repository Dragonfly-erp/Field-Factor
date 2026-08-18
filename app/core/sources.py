# -*- coding: utf-8 -*-
"""Джерела, за якими ріжеться поле.

Кожне джерело віддає одну поверхню на спільній сітці поля. Далі їх можна
брати поодинці або змішувати з вагами — саме тому «комбіноване зонування»
тут не окремий режим, а звичайний випадок цього ж механізму.
"""

import os

import numpy as np

from app.core import satellite

ПОРІГ_ГОЛОГО_ҐРУНТУ = 0.25       # вище цього NDVI поле вже не голе


# ------------------------------------------------------------ службове


def _клієнт():
    import planetary_computer
    from pystac_client import Client

    return Client.open(satellite.КАТАЛОГ, modifier=planetary_computer.sign_inplace)


def _сцени(клієнт, межі, період, максимум_хмар=45, скільки=8):
    пошук = клієнт.search(
        collections=[satellite.КОЛЕКЦІЯ], bbox=межі, datetime=період,
        query={"eo:cloud_cover": {"lt": максимум_хмар}},
    )
    записи = sorted(пошук.items(), key=lambda з: з.properties.get("eo:cloud_cover", 100))
    return записи[:скільки]


def тека_кешу(налаштування, база):
    кеш = (налаштування.get("супутник") or {}).get("кеш") or "кеш_знімків"
    if not os.path.isabs(кеш):
        кеш = os.path.join(база, кеш)
    os.makedirs(кеш, exist_ok=True)
    return кеш


# ------------------------------------------------------------ вегетація


def вегетація_багаторічна(контур, роки, налаштування, база, журнал):
    """Пік вегетації за кожен рік і його багаторічне середнє.

    Культура щороку інша, тож прив'язуватись до її календаря не можна.
    Береться найвище значення NDVI за квітень-серпень: коли б пік не стався,
    він буде спійманий. Розкид між роками — це стабільність місця.
    """
    сітка = satellite.сітка_поля(контур)
    кеш = тека_кешу(налаштування, база)
    межі = tuple(контур.to_crs(4326).total_bounds)

    try:
        клієнт = _клієнт()
    except Exception as помилка:
        return None, {"причина": "каталог знімків недоступний: {}".format(помилка)}

    піки, рядки = [], []
    for рік in роки:
        шари = []
        try:
            записи = _сцени(клієнт, межі, "{}-04-01/{}-09-01".format(рік, рік))
        except Exception as помилка:
            рядки.append({"рік": рік, "сцен": 0, "стан": "пошук не вдався"})
            continue
        for запис in записи:
            try:
                індекси = satellite._прочитати_сцену(запис, сітка, кеш)
            except Exception:
                continue
            if індекси is not None:
                шари.append(індекси["NDVI"])
            if len(шари) >= 5:
                break
        if not шари:
            рядки.append({"рік": рік, "сцен": 0, "стан": "чистих знімків немає"})
            журнал.сказати("  {}: чистих знімків немає".format(рік))
            continue
        with np.errstate(invalid="ignore"):
            піки.append(np.nanmax(np.stack(шари), axis=0).astype("float32"))
        рядки.append({"рік": рік, "сцен": len(шари), "стан": "узято"})
        журнал.сказати("  {}: {} чистих знімків, пік вегетації знято".format(рік, len(шари)))

    if not піки:
        return None, {"причина": "жодного року з придатними знімками", "рядки": рядки}

    стос = np.stack(піки)
    with np.errstate(invalid="ignore"):
        середнє = np.nanmean(стос, axis=0).astype("float32")
        розкид = (np.nanstd(стос, axis=0).astype("float32") if len(піки) > 1
                  else np.zeros_like(середнє))
    return ({"вегетація": середнє, "мінливість_вегетації": розкид, "_сітка": сітка},
            {"років": len(піки), "рядки": рядки})


# ------------------------------------------------------- яскравість ґрунту


def яскравість_ґрунту(контур, роки, налаштування, база, журнал):
    """Те, що видно, коли поле стоїть відкритим.

    Сцена береться не за датою, а за станом поля: якщо медіанний NDVI по
    контуру нижчий за поріг — рослинності фактично немає, і ми дивимось на
    сам ґрунт. Так метод не залежить від того, що там сіяли.
    """
    сітка = satellite.сітка_поля(контур)
    кеш = тека_кешу(налаштування, база)
    межі = tuple(контур.to_crs(4326).total_bounds)

    try:
        клієнт = _клієнт()
    except Exception as помилка:
        return None, {"причина": "каталог знімків недоступний: {}".format(помилка)}

    зібрані, рядки = [], []
    for рік in роки:
        for назва, період in (("рання весна", "{}-03-01/{}-04-20".format(рік, рік)),
                              ("після збирання", "{}-08-15/{}-11-01".format(рік, рік))):
            try:
                записи = _сцени(клієнт, межі, період, максимум_хмар=25, скільки=6)
            except Exception:
                continue
            for запис in записи:
                try:
                    індекси = satellite._прочитати_сцену(запис, сітка, кеш)
                except Exception:
                    continue
                if індекси is None:
                    continue
                медіана = float(np.nanmedian(індекси["NDVI"]))
                if not np.isfinite(медіана) or медіана > ПОРІГ_ГОЛОГО_ҐРУНТУ:
                    continue
                зібрані.append(індекси["ЯСКРАВІСТЬ"])
                рядки.append({"рік": рік, "вікно": назва, "сцена": str(запис.datetime.date()),
                              "ndvi": round(медіана, 3), "стан": "ґрунт відкритий"})
                журнал.сказати("  {} {}: NDVI {:.2f} — ґрунт відкритий".format(
                    рік, назва, медіана))
                break

    if not зібрані:
        return None, {"причина": "не знайшлось жодного знімка з відкритим ґрунтом "
                                 "(NDVI усюди вищий за {})".format(ПОРІГ_ГОЛОГО_ҐРУНТУ),
                      "рядки": рядки}
    with np.errstate(invalid="ignore"):
        середнє = np.nanmean(np.stack(зібрані), axis=0).astype("float32")
    return ({"яскравість_ґрунту": середнє, "_сітка": сітка},
            {"сцен": len(зібрані), "рядки": рядки})


# ------------------------------------------------------------- рельєф


def рельєф(контур, журнал):
    """Висота з Copernicus DEM 30 м, плюс схил і положення в околиці."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    сітка = satellite.сітка_поля(контур)
    межі = tuple(контур.to_crs(4326).total_bounds)
    try:
        клієнт = _клієнт()
        записи = list(клієнт.search(collections=["cop-dem-glo-30"], bbox=межі).items())
    except Exception as помилка:
        return None, {"причина": "DEM недоступний: {}".format(помилка)}
    if not записи:
        return None, {"причина": "покриття DEM на це поле не знайдено"}

    висота = np.full((сітка["висота"], сітка["ширина"]), np.nan, dtype="float32")
    for запис in записи[:4]:
        актив = запис.assets.get("data")
        if актив is None:
            continue
        шматок = np.full_like(висота, np.nan)
        try:
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open(актив.href) as джерело:
                    reproject(source=rasterio.band(джерело, 1), destination=шматок,
                              src_transform=джерело.transform, src_crs=джерело.crs,
                              dst_transform=сітка["перетворення"], dst_crs=сітка["crs"],
                              resampling=Resampling.bilinear, dst_nodata=np.nan)
        except Exception:
            continue
        добрі = np.isfinite(шматок)
        висота[добрі] = шматок[добрі]

    if not np.isfinite(висота).any():
        return None, {"причина": "DEM не прочитався"}

    журнал.сказати("  висота знята з Copernicus DEM 30 м")
    шари = {"висота": висота, "_сітка": сітка}
    шари.update(похідні_рельєфу(висота, сітка["крок"]))
    return шари, {"джерело": "Copernicus DEM GLO-30"}


def похідні_рельєфу(висота, крок):
    """Схил і положення точки відносно околиці — те, що жене воду."""
    from scipy.ndimage import uniform_filter

    заповнена = np.where(np.isfinite(висота), висота, np.nanmedian(висота))
    dy, dx = np.gradient(заповнена, крок)
    схил = np.degrees(np.arctan(np.hypot(dx, dy))).astype("float32")
    околиця = uniform_filter(заповнена, size=max(3, int(round(120 / крок))))
    return {"схил": схил, "положення_в_рельєфі": (заповнена - околиця).astype("float32")}


# ------------------------------------------------------- поверхня з точок


def з_точок(точки, атрибут, сітка, журнал=None, назва=None):
    """Точковий шар (врожайність, EC, агрохімія) → поверхня на сітці поля."""
    from scipy.ndimage import distance_transform_edt, uniform_filter

    рядків, стовпців = сітка["висота"], сітка["ширина"]
    перетворення = сітка["перетворення"]
    xmin, ymax = перетворення.c, перетворення.f
    крок = сітка["крок"]

    x = точки.geometry.x.to_numpy()
    y = точки.geometry.y.to_numpy()
    значення = np.asarray(точки[атрибут], dtype="float64")
    добрі = np.isfinite(значення)
    x, y, значення = x[добрі], y[добрі], значення[добрі]
    if not len(значення):
        return None

    рядки = np.clip(((ymax - y) / крок).astype("int64"), 0, рядків - 1)
    стовпці = np.clip(((x - xmin) / крок).astype("int64"), 0, стовпців - 1)
    ключ = рядки * стовпців + стовпці
    сума = np.bincount(ключ, weights=значення, minlength=рядків * стовпців)
    кількість = np.bincount(ключ, minlength=рядків * стовпців)

    поверхня = np.full(рядків * стовпців, np.nan)
    заповнені = кількість > 0
    поверхня[заповнені] = сума[заповнені] / кількість[заповнені]
    поверхня = поверхня.reshape(рядків, стовпців).astype("float32")

    порожні = ~np.isfinite(поверхня)
    if порожні.any() and (~порожні).any():
        _, індекси = distance_transform_edt(порожні, return_indices=True)
        поверхня[порожні] = поверхня[індекси[0][порожні], індекси[1][порожні]]
    # легке згладжування, щоб окремий запис не робив власної зони
    поверхня = uniform_filter(поверхня, size=3).astype("float32")

    if журнал:
        журнал.сказати("  {}: {} записів лягли на сітку {} м".format(
            назва or атрибут, len(значення), крок))
    return поверхня
