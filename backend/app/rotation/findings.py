"""Short plain statements about what stands out on this field (Req 4, 17.9).

Each finding comes from one written rule with a threshold, and cites the values it used with
their source and resolution. Rules run in priority order and the first 6 that apply are kept.
A rule whose data is missing is skipped; the others still run (Req 4.6).
"""
from app.rotation.site_facts import WET_DRAINAGE, SiteFacts, frequency_at_least

MAX_FINDINGS = 6
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def _trend_items(trends):
    return {i["id"]: i for i in (trends or {}).get("indicators", [])}


def _trend_cite(trends, item, units):
    return {"value": item.get("per_decade"), "units": f"{units} per decade", "source": trends.get("source", "NASA POWER"),
            "resolution_m": trends.get("resolution_m"), "period": item.get("years") or trends.get("period")}


def rising_heat(facts, trends, outlook, current_calendar):
    hot = _trend_items(trends).get("hot_days")
    if not hot or not hot.get("clear") or (hot.get("per_decade") or 0) < 3:
        return None
    return {
        "id": "rising_heat", "title": "Hot days are rising",
        "text": (f"About {hot['per_decade']:.0f} more days above 35 °C per decade since {hot['years'][:4]}: "
                 f"from {hot['first_decade_avg']:.0f} a year in the first decade to {hot['last_decade_avg']:.0f} a year in the last."),
        "evidence": [_trend_cite(trends, hot, "days")], "terms": ["hot_day", "clear_change"],
    }


def warm_nights(facts, trends, outlook, current_calendar):
    item = _trend_items(trends).get("warm_nights")
    if not item or not item.get("clear") or (item.get("per_decade") or 0) <= 0:
        return None
    return {
        "id": "warm_nights", "title": "Nights are staying warmer",
        "text": (f"Nights above 24 °C went from {item['first_decade_avg']:.0f} to {item['last_decade_avg']:.0f} a year. "
                 "Warm nights stress crops and livestock because they never get to cool down."),
        "evidence": [_trend_cite(trends, item, "nights")], "terms": ["warm_night", "clear_change"],
    }


def fewer_frosts(facts, trends, outlook, current_calendar):
    item = _trend_items(trends).get("frost_days")
    if not item or not item.get("clear") or (item.get("per_decade") or 0) >= 0:
        return None
    return {
        "id": "fewer_frosts", "title": "Fewer frosts each winter",
        "text": (f"Frost days fell from {item['first_decade_avg']:.0f} to {item['last_decade_avg']:.0f} a year. "
                 "A longer cool season helps winter cover crops, but more insects and weeds can survive the winter."),
        "evidence": [_trend_cite(trends, item, "days")], "terms": ["frost_day", "clear_change"],
    }


def outlook_heat(facts, trends, outlook, current_calendar):
    item = {i["id"]: i for i in (outlook or {}).get("indicators", [])}.get("hot_days")
    if not item or item["change"]["mid"] < 10:
        return None
    c = item["change"]
    future = item.get("future_value")
    text = (f"Climate models project {c['low']:.0f} to {c['high']:.0f} more days above 35 °C a year in "
            f"{outlook.get('future', '2030-2049')} than in {outlook.get('recent', '1991-2020')}")
    text += f", about {future['mid']:.0f} a year." if future else "."
    return {
        "id": "outlook_heat", "title": "More heat ahead",
        "text": text,
        "evidence": [{"value": c["mid"], "units": "more days/year (middle model)", "source": outlook.get("source"),
                      "resolution_m": (outlook.get("resolution_km") or 10) * 1000, "period": outlook.get("future")}],
        "terms": ["climate_projection"],
    }


def slow_soak(facts: SiteFacts, trends, outlook, current_calendar):
    group = str(facts.hydro_group.value) if facts.hydro_group else ""
    wet = facts.drainage and str(facts.drainage.value).lower() in WET_DRAINAGE
    if not (group.startswith(("C", "D")) or wet):
        return None
    evidence = [f.cite() for f in (facts.hydro_group, facts.drainage) if f]
    return {
        "id": "slow_soak", "title": "Rain soaks in slowly",
        "text": (f"Rain soaks into this soil slowly (soil group {group or 'unknown'}"
                 + (f" and is {str(facts.drainage.value).lower()}" if facts.drainage else "")
                 + ". Heavy rain runs off instead of soaking in, so living cover and plant leftovers matter more here."),
        "evidence": evidence, "terms": ["hydrologic_group", "drainage_class"],
    }


def flood_risk(facts: SiteFacts, trends, outlook, current_calendar):
    hits = [f for f in (facts.flooding, facts.ponding) if f and frequency_at_least(f.value, "occasional")]
    if not hits:
        return None
    what = " and ".join(("floods" if f is facts.flooding else "ponds") + f" {f.value}ly" for f in hits)
    return {
        "id": "flood_risk", "title": "The field can flood",
        "text": f"The soil survey says this soil {what}. Crops that cannot stand wet roots were ruled out.",
        "evidence": [f.cite() for f in hits], "terms": ["flooding_frequency"],
    }


def erosion_risk(facts: SiteFacts, trends, outlook, current_calendar):
    k = facts.k_factor.value if facts.k_factor else None
    slope = facts.slope_high.value if facts.slope_high else None
    if not ((isinstance(k, (int, float)) and k >= 0.32) or (isinstance(slope, (int, float)) and slope >= 8)):
        return None
    return {
        "id": "erosion_risk", "title": "This soil erodes easily",
        "text": f"The soil wash-away rating (K factor) is {k:g}" + (f" on slopes up to {slope:g}%" if slope is not None else "") + ". Keep the soil covered, especially in the wettest months.",
        "evidence": [f.cite() for f in (facts.k_factor, facts.slope_high) if f], "terms": ["k_factor"],
    }


def low_om(facts: SiteFacts, trends, outlook, current_calendar):
    if not facts.om_pct or not isinstance(facts.om_pct.value, (int, float)) or facts.om_pct.value >= 2:
        return None
    return {
        "id": "low_om", "title": "Not much plant material in the soil",
        "text": f"The surface soil is about {facts.om_pct.value:g}% made of plant and animal material. Living roots and plant leftovers build it up over the years.",
        "evidence": [facts.om_pct.cite()], "terms": ["organic_matter"],
    }


def bare_soil(facts: SiteFacts, trends, outlook, current_calendar):
    if not current_calendar:
        return None
    cells = [c for year in current_calendar for c in year]
    bare_wettest = [c for c in cells if c["bare"] and c["wettest"]]
    longest = run = 0
    for c in cells + cells[:12]:  # wrap around the new year
        run = run + 1 if c["bare"] else 0
        longest = max(longest, run)
    longest = min(longest, len(cells))
    if not bare_wettest and longest < 2:
        return None
    parts = []
    if bare_wettest:
        parts.append(f"the wettest month ({MONTHS[bare_wettest[0]['month'] - 1]})")
    if longest >= 2:
        parts.append(f"{longest} months in a row")
    return {
        "id": "bare_soil", "title": "Bare soil in your current rotation",
        "text": f"The current rotation leaves the soil bare for {' and '.join(parts)}. Bare soil loses topsoil and water.",
        "evidence": [facts.wettest_month.cite()] if facts.wettest_month else [{"value": longest, "units": "months bare",
                                                                               "source": "crop calendar", "resolution_m": None, "period": ""}],
        "terms": ["cover_crop"],
    }


def rain_variable(facts: SiteFacts, trends, outlook, current_calendar):
    if not facts.rain_cv or facts.rain_cv.value < 20:
        return None
    total = f" around an average of {facts.rain_total.value:.0f} mm" if facts.rain_total else ""
    return {
        "id": "rain_variable", "title": "Rain swings a lot from year to year",
        "text": f"Yearly rain varies by about {facts.rain_cv.value:.0f}%{total}. Plan for dry years, not the average.",
        "evidence": [facts.rain_cv.cite()], "terms": ["variation"],
    }


def drying(facts, trends, outlook, current_calendar):
    items = _trend_items(trends)
    for key, label, units in (("soil_wetness", "Soil wetness near roots", "0–1"), ("water_balance", "Rain minus evaporation", "mm")):
        item = items.get(key)
        if item and item.get("clear") and (item.get("per_decade") or 0) < 0:
            return {
                "id": "drying", "title": "The soil is drying out",
                "text": f"{label} has likely been going down since {item['years'][:4]} (NASA weather model).",
                "evidence": [_trend_cite(trends, item, units)], "terms": ["soil_wetness"],
            }
    return None


RULES = [rising_heat, warm_nights, fewer_frosts, outlook_heat, slow_soak, flood_risk,
         erosion_risk, low_om, bare_soil, rain_variable, drying]


def findings(facts: SiteFacts, trends: dict | None, outlook: dict | None, current_calendar=None) -> list[dict]:
    """Up to 6 findings in priority order. Each has id, title, text, evidence, terms."""
    out = []
    for rule in RULES:
        try:
            result = rule(facts, trends, outlook, current_calendar)
        except (KeyError, TypeError, ValueError):
            result = None  # incomplete data for this rule: skip it, keep the others
        if result and result["evidence"]:
            out.append(result)
        if len(out) == MAX_FINDINGS:
            break
    return out
