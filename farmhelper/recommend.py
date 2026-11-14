"""Turn NASA climate data + soil into planting windows and plain-language advice.

Rules of thumb, not agronomy: every recommendation carries the reason it was made, and the
page points to the state's extension service (found via SerpAPI) for local confirmation.
"""

from datetime import date

def f(c):
    """°C -> rounded °F (the page is for US farmers)."""
    return round(c * 9 / 5 + 32)


def inch(mm):
    return f"{mm / 25.4:.1f} in"


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# plant_c:  monthly mean air temperature (°C) range in which to plant / sow
# grow_c:   range in which the crop keeps growing until harvest
# days:     days from planting to harvest
# ph:       soil pH range it does well in
# water:    low / medium / high
CROPS = [
    # cool-season
    {"name": "Lettuce", "kind": "Vegetable", "plant_c": (7, 20), "grow_c": (7, 24), "days": 50, "ph": (6.0, 7.0), "water": "medium"},
    {"name": "Spinach", "kind": "Vegetable", "plant_c": (5, 18), "grow_c": (4, 24), "days": 45, "ph": (6.5, 7.5), "water": "medium"},
    {"name": "Peas", "kind": "Vegetable", "plant_c": (7, 18), "grow_c": (7, 24), "days": 65, "ph": (6.0, 7.5), "water": "medium"},
    {"name": "Broccoli", "kind": "Vegetable", "plant_c": (10, 20), "grow_c": (7, 24), "days": 75, "ph": (6.0, 7.0), "water": "medium"},
    {"name": "Carrots", "kind": "Vegetable", "plant_c": (8, 21), "grow_c": (7, 26), "days": 75, "ph": (6.0, 7.0), "water": "medium"},
    {"name": "Onions", "kind": "Vegetable", "plant_c": (7, 20), "grow_c": (5, 30), "days": 110, "ph": (6.0, 7.0), "water": "medium"},
    {"name": "Cabbage", "kind": "Vegetable", "plant_c": (8, 20), "grow_c": (6, 24), "days": 80, "ph": (6.0, 7.5), "water": "medium"},
    {"name": "Winter wheat", "kind": "Field crop", "plant_c": (8, 18), "grow_c": (-15, 28), "days": 240, "ph": (6.0, 7.5), "water": "low", "fall_sown": True},
    # warm-season
    {"name": "Tomatoes", "kind": "Vegetable", "plant_c": (18, 29), "grow_c": (15, 32), "days": 80, "ph": (6.0, 6.8), "water": "high"},
    {"name": "Peppers", "kind": "Vegetable", "plant_c": (20, 29), "grow_c": (16, 32), "days": 75, "ph": (6.0, 7.0), "water": "medium"},
    {"name": "Sweet corn", "kind": "Vegetable", "plant_c": (16, 30), "grow_c": (15, 33), "days": 85, "ph": (5.8, 7.0), "water": "high"},
    {"name": "Green beans", "kind": "Vegetable", "plant_c": (18, 29), "grow_c": (15, 32), "days": 55, "ph": (6.0, 7.0), "water": "medium"},
    {"name": "Squash", "kind": "Vegetable", "plant_c": (18, 30), "grow_c": (15, 33), "days": 55, "ph": (6.0, 7.5), "water": "medium"},
    {"name": "Watermelon", "kind": "Fruit", "plant_c": (21, 32), "grow_c": (18, 35), "days": 85, "ph": (6.0, 7.0), "water": "medium"},
    {"name": "Cotton", "kind": "Field crop", "plant_c": (18, 32), "grow_c": (15, 35), "days": 150, "ph": (5.8, 8.0), "water": "low"},
    {"name": "Grain sorghum", "kind": "Field crop", "plant_c": (18, 32), "grow_c": (15, 35), "days": 110, "ph": (5.5, 8.5), "water": "low"},
    {"name": "Peanuts", "kind": "Field crop", "plant_c": (20, 30), "grow_c": (16, 33), "days": 130, "ph": (5.8, 7.0), "water": "medium"},
]


def planting_months(crop, temps):
    """12 booleans: can this crop be planted that month and finish before conditions turn?"""
    lo, hi = crop["plant_c"]
    glo, ghi = crop["grow_c"]
    months_needed = max(1, round(crop["days"] / 30))
    good = []
    for m in range(12):
        ok = lo <= temps[m] <= hi
        if ok and crop.get("fall_sown"):
            ok = temps[(m + 1) % 12] < temps[m]  # sow while it's cooling into winter
        if ok and not crop.get("fall_sown"):
            ok = all(glo <= temps[(m + k) % 12] <= ghi for k in range(1, months_needed))
        good.append(ok)
    return good


def _next_good(good, month):
    for k in range(1, 12):
        if good[(month + k) % 12]:
            return (month + k) % 12, k
    return None, None


def crop_plan(climate, soil, month=None):
    month = date.today().month - 1 if month is None else month
    temps = climate["temp_c"]
    ph = (soil or {}).get("ph")
    annual_rain = climate["annual_rain_mm"]
    plans = []
    for crop in CROPS:
        good = planting_months(crop, temps)
        if good[month]:
            status, when = "now", f"Plant in {MONTH_NAMES[month]}"
        else:
            nxt, wait = _next_good(good, month)
            if nxt is None:
                status, when = "unsuited", "Climate doesn't fit"
            else:
                status = "soon" if wait <= 2 else "later"
                when = f"Plant in {MONTH_NAMES[nxt]}"
        reasons = []
        lo, hi = crop["plant_c"]
        reasons.append(f"Plant when months average {f(lo)}–{f(hi)}°F; this month averages {f(temps[month])}°F.")
        soil_ok = True
        if ph is not None:
            plo, phi = crop["ph"]
            if ph < plo:
                soil_ok = False
                reasons.append(f"Soil pH {ph} is below its {plo}–{phi} range: add lime.")
            elif ph > phi:
                soil_ok = False
                reasons.append(f"Soil pH {ph} is above its {plo}–{phi} range: expect weaker growth.")
            else:
                reasons.append(f"Soil pH {ph} suits it ({plo}–{phi}).")
        if crop["water"] == "high" and annual_rain < 600:
            reasons.append(f"Needs a lot of water and you average {inch(annual_rain)} of rain a year: plan to irrigate.")
        elif crop["water"] == "low" and annual_rain < 600:
            reasons.append("Handles dry conditions well.")
        plans.append({
            "crop": crop["name"], "kind": crop["kind"], "status": status, "when": when,
            "months": good, "days": crop["days"], "water": crop["water"],
            "soil_ok": soil_ok, "reasons": reasons,
        })
    order = {"now": 0, "soon": 1, "later": 2, "unsuited": 3}
    plans.sort(key=lambda p: (order[p["status"]], not p["soil_ok"], p["crop"]))
    return plans


def soil_advice(soil):
    tips = []
    if not soil or soil.get("ph") is None:
        return [{"level": "info", "title": "Get a soil test", "text": "We couldn't find soil data for this exact spot. A soil test from your county extension office tells you pH and nutrients for a few dollars."}]
    ph, clay, sand, om = soil.get("ph"), soil.get("clay"), soil.get("sand"), soil.get("organic_matter")
    if ph < 5.8:
        tips.append({"level": "warn", "title": "Acidic soil", "text": f"pH {ph} is acidic. Agricultural lime raises pH; most crops prefer 6.0–7.0."})
    elif ph > 7.8:
        tips.append({"level": "warn", "title": "Alkaline soil", "text": f"pH {ph} is alkaline. Iron and zinc get harder for plants to take up. Sorghum, cotton and spinach tolerate it; sulfur and compost lower pH slowly."})
    else:
        tips.append({"level": "good", "title": "pH is workable", "text": f"pH {ph} works for most crops."})
    if clay is not None and clay >= 35:
        tips.append({"level": "warn", "title": "Heavy clay", "text": f"{clay:.0f}% clay holds water but drains slowly and packs down. Avoid working it wet; raised beds and organic matter help."})
    elif sand is not None and sand >= 60:
        tips.append({"level": "warn", "title": "Sandy soil", "text": f"{sand:.0f}% sand drains fast and loses nutrients. Water and fertilize in smaller, more frequent doses; compost helps it hold water."})
    if om is not None:
        if om < 2:
            tips.append({"level": "warn", "title": "Low organic matter", "text": f"Organic matter is {om}%. Cover crops (rye, clover) and compost build it up, improving water holding and nutrients."})
        else:
            tips.append({"level": "good", "title": "Organic matter", "text": f"Organic matter is {om}%, a decent level. Keep it up with residue and cover crops."})
    drainage = (soil.get("drainage") or "").lower()
    if "poorly" in drainage:
        tips.append({"level": "warn", "title": "Poor drainage", "text": f"USDA rates this soil \"{soil['drainage']}\". Roots can drown in wet spells: use raised beds or drainage."})
    return tips


def conditions_advice(climate, recent, month=None):
    month = date.today().month - 1 if month is None else month
    tips = []
    if not recent:
        return tips
    normal_30 = climate["rain_mm"][month]
    rain = recent["rain_mm"]
    if rain < 0.5 * normal_30:
        tips.append({"level": "warn", "title": "Drier than normal", "text": f"{inch(rain)} of rain in the last {recent['days']} days, versus about {inch(normal_30)} in a normal month. Plan to irrigate new plantings."})
    elif rain > 1.5 * normal_30:
        tips.append({"level": "info", "title": "Wetter than normal", "text": f"{inch(rain)} of rain in the last {recent['days']} days, versus about {inch(normal_30)} normally. Wait for fields to dry before working the soil."})
    else:
        tips.append({"level": "good", "title": "Normal rainfall", "text": f"{inch(rain)} of rain in the last {recent['days']} days, close to the usual {inch(normal_30)}."})
    top = recent.get("topsoil_moisture")
    if top is not None:
        if top < 0.3:
            tips.append({"level": "warn", "title": "Dry topsoil", "text": f"NASA satellite soil moisture for the top layer is {top:.2f} (0 = dry, 1 = soaked). Seeds need moisture to sprout: water before or right after planting."})
        elif top > 0.75:
            tips.append({"level": "info", "title": "Wet topsoil", "text": f"Topsoil moisture is {top:.2f} (0 = dry, 1 = soaked). Heavy equipment can compact wet soil."})
    low = recent.get("low_c_7day")
    if low is not None and low <= 0:
        tips.append({"level": "warn", "title": "Frost in the last week", "text": f"It dropped to {f(low)}°F in the last 7 days. Protect tender plants (tomatoes, peppers, beans) or wait to plant them."})
    return tips
