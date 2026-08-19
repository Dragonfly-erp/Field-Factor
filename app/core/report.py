# -*- coding: utf-8 -*-
"""Звіт для господарства.

Технічний `zones_summary.txt` пишеться для нас: там провенанс, пороги і
методи. Це — інше. Це те, що лишається на столі після зустрічі, і читати
його буде людина, яка не відкриє ГІС і не має відкривати.

Тому тут немає жодного слова, яке треба пояснювати, і є головна теза, без
якої вся робота втрачає сенс: **слабка зона не означає, що туди треба
вкладати більше.** Що саме туди треба — покажуть зразки, а не карта.
"""

import html
import os
from datetime import datetime

КОЛЬОРИ = ["#9c5a35", "#c08a4a", "#d9bd6b", "#a8c95c", "#7bab4c",
           "#4b8b3c", "#3a7a35", "#2f6b30", "#255c2c", "#1c4a25"]

# Як називати шматок ландшафту за його номером у ряду
ІМЕНА = ["здуті вершини", "верхні схили", "середні схили", "нижні схили",
         "перехід до низу", "низи", "вологі низи", "западини",
         "глибокі западини", "мокрі западини"]

ПОЯСНЕННЯ = {
    "EC_SH": "електропровідність, мала глибина",
    "EC_DP": "електропровідність, велика глибина",
    "TWI_AVG": "де вода затримується",
    "CURV_AVG": "вершина чи улоговина",
    "ELEV_AVG": "висота, м",
    "SLOPE_AVG": "схил, градусів",
    "VEG_AVG": "багаторічна вегетація",
    "VEG_STD": "мінливість вегетації між роками",
    "SOIL_BRT": "яскравість голого ґрунту",
    "YLD_KGHA": "врожайність, кг/га",
    "YLD_AVG": "врожайність, кг/га",
}


def _ім_я_зони(номер, усього):
    """Розтягуємо ряд імен на наявну кількість зон: перша завжди вершина,
    остання завжди западина, скільки б їх не було."""
    if усього <= 1:
        return "поле цілком"
    місце = (номер - 1) / (усього - 1)
    return ІМЕНА[min(len(ІМЕНА) - 1, int(round(місце * (len(ІМЕНА) - 1))))]


def _колір(номер, усього):
    if усього <= 1:
        return КОЛЬОРИ[len(КОЛЬОРИ) // 2]
    місце = (номер - 1) / (усього - 1)
    return КОЛЬОРИ[min(len(КОЛЬОРИ) - 1, int(round(місце * (len(КОЛЬОРИ) - 1))))]


def _е(текст):
    return html.escape(str(текст), quote=True)


def _ч(значення, знаків=2):
    """Українське число: кома, а не крапка."""
    if значення is None:
        return "—"
    return ("{:." + str(знаків) + "f}").format(значення).replace(".", ",")


def скласти(сеанс, підсумок, шлях):
    """Пише HTML-звіт. Повертає шлях до файлу."""
    паспорт = сеанс.паспорт
    зони = підсумок.get("зони_таблиця") or []
    усього = len(зони)
    площа = sum(з.get("AREA_HA") or 0 for з in зони)
    перевірка = підсумок.get("перевірка") or []
    відбір = підсумок.get("відбір") or []
    джерела = підсумок.get("джерела") or []

    показники = [к for к in (зони[0].keys() if зони else [])
                 if к not in ("ZONE_ID", "AREA_HA")]

    ч = []
    д = ч.append
    д("<!doctype html><html lang='uk'><head><meta charset='utf-8'>")
    д("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    д("<title>{} · що показало поле</title>".format(_е(паспорт.get("поле") or "Поле")))
    д("<style>" + _стилі() + "</style></head><body>")

    д("<header><div class='шапка-ряд'>")
    д("<div><div class='марка'><b>Field</b>Factor</div>"
      "<div class='гасло'>Data. Insight. Growth.</div></div>")
    д("<div class='дата'>{}</div>".format(datetime.now().strftime("%d.%m.%Y")))
    д("</div></header><main>")

    д("<h1>Поле {} працює не одним шматком</h1>".format(_е(паспорт.get("поле") or "")))
    перелік = [д_["джерело"] for д_ in джерела] or ["обстеження поля"]
    підстава = (перелік[0] if len(перелік) == 1
                else ", ".join(перелік[:-1]) + " і " + перелік[-1])
    д("<p class='ліда'>Ми дивились на нього через {}. Ось що виявилось — "
      "і що з цього випливає для витрат.</p>".format(_е(підстава)))

    д("<div class='трійка'>")
    д("<div><div class='велике'>{}</div><p>гектарів обстежено</p></div>".format(_ч(площа, 1)))
    д("<div><div class='велике'>{}</div><p>зон, які поводяться по-різному</p></div>".format(усього))
    if перевірка:
        д("<div><div class='велике'>{:.0f} %</div><p>різниці врожаю пояснюють "
          "ці зони</p></div>".format(перевірка[0]["пояснено"]))
    else:
        д("<div><div class='велике'>{}</div><p>місць для відбору зразків</p></div>".format(
            len(відбір) or "—"))
    д("</div>")

    if усього:
        д("<div class='мітка'>Від найсухішого до найвологішого</div>")
        д("<div class='смуга'>")
        for з in зони:
            частка = (з.get("AREA_HA") or 0) / max(площа, 0.001) * 100
            д("<i style='flex:0 0 {:.2f}%;background:{}'>{}</i>".format(
                частка, _колір(з["ZONE_ID"], усього), з["ZONE_ID"]))
        д("</div>")

        д("<table><thead><tr><th>Зона</th><th>Що це</th><th>Площа</th>")
        for п in показники:
            д("<th>{}</th>".format(_е(ПОЯСНЕННЯ.get(п, п))))
        д("</tr></thead><tbody>")
        for з in зони:
            д("<tr><td><b style='background:{}'>{}</b></td>".format(
                _колір(з["ZONE_ID"], усього), з["ZONE_ID"]))
            д("<td>{}</td>".format(_е(_ім_я_зони(з["ZONE_ID"], усього))))
            д("<td class='число'>{} га</td>".format(_ч(з.get("AREA_HA") or 0)))
            for п in показники:
                значення = з.get(п)
                д("<td class='число'>{}</td>".format(
                    "—" if значення is None else _ч(значення, 2 if abs(значення) < 100 else 0)))
            д("</tr>")
        д("</tbody></table>")

    д("<div class='головне'><h2>Слабка зона — не привід вкладати більше</h2>"
      "<p>Те, що ділянка виглядає гіршою, ще не означає, що їй бракує поживи. "
      "Часто там уже досить і фосфору, і калію, а врожай тримає зовсім інше — "
      "кислотність, вода або ущільнення. І навпаки: найкраща зона поля роками "
      "виносить найбільше, і саме їй може бракувати найпершою.</p>"
      "<p><strong>Що саме потрібно кожній зоні, покаже аналіз ґрунту, "
      "а не карта.</strong> Карта каже, де брати зразок, щоб він відповідав "
      "за свій шматок поля, а не за середнє по лікарні.</p></div>")

    if відбір:
        д("<div class='мітка'>Куди їхати по зразки</div>")
        д("<table class='вузька'><thead><tr><th>Зразок</th><th>Відповідає за зони</th>"
          "<th>Площа</th><th>Від межі</th></tr></thead><tbody>")
        for т in відбір:
            д("<tr><td><b style='background:#8a7350'>{}</b></td><td>{}</td>"
              "<td class='число'>{} га</td><td class='число'>{} м</td></tr>".format(
                  т["група"], _е(т["зони"]), _ч(т["площа_га"]), _ч(т["від_межі_м"], 1)))
        д("</tbody></table>")
        д("<p class='дрібно'>Точка стоїть у серцевині своєї групи, подалі від меж — "
          "там, де ґрунт уже перехідний, зразок нічого не показує.</p>")

    if перевірка:
        д("<div class='перевірка'><div class='мітка'>Звідки впевненість</div>")
        for п in перевірка:
            д("<p>Ці зони будувались <strong>без</strong> даних про врожай. "
              "Коли ми потім наклали на них {} — виявилось, що вони пояснюють "
              "<strong>{:.0f} %</strong> різниці. Тобто поле справді поводиться "
              "так, як показує карта.</p>".format(_е(п["шар"]), п["пояснено"]))
        д("</div>")

    д("<footer><p>{}</p><p class='дрібно'>Звіт склала програма FieldFactor. "
      "Числа взяті з обстеження цього поля; там, де даних не було, у таблиці "
      "стоїть прочерк, а не припущення.</p></footer>".format(
          _е(підсумок.get("пояснення") or "")))
    д("</main></body></html>")

    with open(шлях, "w", encoding="utf-8") as ф:
        ф.write("\n".join(ч))
    return шлях


def _стилі():
    return """
:root{--папір:#f4f2ec;--полотно:#fff;--рамка:#ddd9cc;--чорнило:#241f18;
--тихе:#6d6656;--зелень:#3e7a32;--темна:#1e4d2b;--мʼяка:#edf2e6;--глина:#8a7350}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){
--папір:#16150f;--полотно:#1e1d16;--рамка:#35332a;--чорнило:#ece8dc;
--тихе:#9a9484;--зелень:#7fb75f;--темна:#a7d08a;--мʼяка:#21291c;--глина:#b09772}}
*{box-sizing:border-box}
body{margin:0;background:var(--папір);color:var(--чорнило);
font:16px/1.6 "Segoe UI",system-ui,sans-serif}
header{background:var(--полотно);border-bottom:1px solid var(--рамка);padding:20px 32px}
.шапка-ряд{max-width:760px;margin:0 auto;display:flex;align-items:center;gap:16px}
.марка{font-family:Georgia,serif;font-size:24px}
.марка b{color:var(--темна)}
.гасло{font-size:9.5px;letter-spacing:.3em;text-transform:uppercase;
color:var(--зелень);font-weight:700;margin-top:2px}
.дата{margin-left:auto;color:var(--тихе);font-size:14px}
main{max-width:760px;margin:0 auto;padding:34px 32px 70px}
h1{font-family:Georgia,serif;font-size:29px;line-height:1.2;margin:0 0 10px;
text-wrap:balance}
h2{font-family:Georgia,serif;font-size:20px;margin:0 0 8px}
.ліда{color:var(--тихе);margin:0 0 28px;max-width:52ch}
.трійка{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin:0 0 32px}
.велике{font-family:Georgia,serif;font-size:44px;font-weight:700;line-height:1;
color:var(--темна)}
.трійка p{font-size:13px;color:var(--тихе);margin:4px 0 0}
.мітка{font-size:10.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
color:var(--тихе);margin:30px 0 8px}
.смуга{display:flex;height:32px;border-radius:3px;overflow:hidden;margin-bottom:22px}
.смуга i{display:grid;place-items:center;color:#fff;font-size:11px;font-weight:700;
font-style:normal}
table{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:8px}
th{text-align:left;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
color:var(--тихе);font-weight:700;padding:0 8px 8px;border-bottom:1px solid var(--рамка)}
td{padding:10px 8px;border-bottom:1px solid var(--рамка)}
td b{display:grid;place-items:center;width:24px;height:24px;border-radius:3px;
color:#fff;font-size:12px}
.число{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.вузька td,.вузька th{padding-left:0}
.головне{background:var(--мʼяка);border-left:3px solid var(--зелень);
padding:20px 24px;margin:34px 0;border-radius:0 4px 4px 0}
.головне p{margin:0 0 10px;font-size:15px}
.головне p:last-child{margin-bottom:0}
.перевірка{border-top:1px solid var(--рамка);margin-top:34px;padding-top:8px}
.перевірка p{font-size:15px}
.дрібно{font-size:13px;color:var(--тихе)}
footer{border-top:1px solid var(--рамка);margin-top:40px;padding-top:20px;
font-size:13.5px;color:var(--тихе)}
@media print{body{background:#fff}header{border:none}main{padding-top:10px}}
"""
