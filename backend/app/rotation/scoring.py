"""Six 0-100 scores for each rotation, with the parts of each formula shown (Req 10).

The scores compare options for THIS field. They are a rough, transparent guide built from
the crop table's low/medium/high attributes and the field's facts, not a yield model.

  water    100 - average water need of the crops in the ground; minus 20 if a high-water crop
           grows in a heat-stress month without irrigation; plus 10 if every crop is drought tolerant
  soil     40 x share of months with living roots + 20 if a legume is included
           + 20 x average residue + 20 if any crop roots deep
  erosion  100 x share of months with cover, weighted by each crop's erosion protection, with the
           wettest month counted twice; then reduced on fields that erode easily
           (x (1 - 0.5 x site risk), site risk = the larger of K / 0.5 and top slope / 15, at most 1)
  forage   average forage value over all months (0 when there is no livestock)
  income   average income level of the crops (none/low/medium/high), a rough guide without prices
  passes   100 - 10 x (field passes per year - 1)

Overall: a weighted average where the scores linked to the farmer's priorities count double.
Outlook: the same formulas with the 2030-2049 facts, minus 15 for each crop at future risk.
"""
LEVEL = {"low": 0.0, "medium": 0.5, "high": 1.0}
VALUE = {"none": 0.0, "low": 1 / 3, "medium": 2 / 3, "high": 1.0}
ROOT = {"shallow": 0.0, "medium": 0.5, "deep": 1.0}

DIMENSIONS = ("water", "soil", "erosion", "forage", "income", "passes")
LABELS = {
    "water": "Water use", "soil": "Soil building", "erosion": "Erosion protection",
    "forage": "Grazing and hay", "income": "Income potential (rough)", "passes": "Fewer trips across the field",
}
# Which scores each farmer priority makes count double (Req 10.3).
PRIORITY_DIMENSIONS = {
    "save_water": ("water",),
    "build_soil": ("soil", "erosion"),
    "forage": ("forage",),
    "income": ("income",),
    "fewer_passes": ("passes",),
}
FUTURE_RISK_PENALTY = 15


def _clamp(x: float) -> int:
    return int(round(max(0.0, min(100.0, x))))


def _cells(cal):
    return [cell for year in cal for cell in year]


def score_water(cal, crops, facts, irrigation):
    occupied = [c for c in _cells(cal) if c["crop_ids"]]
    if not occupied:
        return 100, [{"label": "No crop in the ground", "points": 100}]
    need = sum(max(LEVEL[crops[i]["water_need"]] for i in c["crop_ids"]) for c in occupied) / len(occupied)
    parts = [{"label": f"Average crop water need ({need:.2f} on a scale from 0 to 1)", "points": round(100 - 100 * need)}]
    total = 100 - 100 * need
    hot_thirsty = sorted({crops[i]["name"] for c in occupied if c["heat"] for i in c["crop_ids"]
                          if crops[i]["water_need"] == "high"})
    if hot_thirsty and not irrigation:
        total -= 20
        parts.append({"label": f"High-water crop in a very hot month without irrigation ({', '.join(hot_thirsty)})", "points": -20})
    ids = {i for c in occupied for i in c["crop_ids"]}
    if ids and all(crops[i]["drought_tolerance"] == "high" for i in ids):
        total += 10
        parts.append({"label": "Every crop is drought tolerant", "points": 10})
    return _clamp(total), parts


def score_soil(cal, crops, strategy):
    cells = _cells(cal)
    rooted = sum(1 for c in cells if c["crop_ids"]) / len(cells)
    ids = strategy["crop_ids"]
    legume = any(crops[i]["nitrogen_fixing"] for i in ids)
    residue = sum(LEVEL[crops[i]["residue"]] for i in ids) / len(ids) if ids else 0
    deep = any(crops[i]["root_depth"] == "deep" for i in ids)
    parts = [
        {"label": f"Living roots in {rooted:.0%} of months", "points": round(40 * rooted)},
        {"label": "Includes a nitrogen-fixing legume" if legume else "No legume", "points": 20 if legume else 0},
        {"label": f"Average plant material left on the soil ({residue:.2f} on a scale from 0 to 1)", "points": round(20 * residue)},
        {"label": "Has a deep-rooted crop" if deep else "No deep-rooted crop", "points": 20 if deep else 0},
    ]
    return _clamp(sum(p["points"] for p in parts)), parts


def score_erosion(cal, crops, facts):
    weighted = total_weight = 0.0
    for c in _cells(cal):
        weight = 2.0 if c["wettest"] else 1.0
        cover = max((LEVEL[crops[i]["erosion_protection"]] for i in c["crop_ids"]), default=0.0)
        weighted += weight * cover
        total_weight += weight
    base = 100 * weighted / total_weight if total_weight else 0
    parts = [{"label": "Months with soil cover (wettest month counts twice)", "points": round(base)}]
    risks = []
    if facts.k_factor and isinstance(facts.k_factor.value, (int, float)):
        risks.append(facts.k_factor.value / 0.5)
    if facts.slope_high and isinstance(facts.slope_high.value, (int, float)):
        risks.append(facts.slope_high.value / 15)
    site_risk = min(1.0, max(risks)) if risks else 0.0
    if site_risk:
        reduction = base * 0.5 * site_risk
        parts.append({"label": f"Soil is more likely to wash away here (risk score {site_risk:.2f})", "points": -round(reduction)})
        base -= reduction
    return _clamp(base), parts


def score_forage(cal, crops, livestock):
    if livestock == "no":
        return 0, [{"label": "You have no livestock", "points": 0}]
    cells = _cells(cal)
    value = sum(max((VALUE[crops[i]["forage_value"]] for i in c["crop_ids"]), default=0.0) for c in cells) / len(cells)
    return _clamp(100 * value), [{"label": f"Average grazing and hay value across the year ({value:.2f} on a scale from 0 to 1)",
                                  "points": round(100 * value)}]


def score_income(crops, strategy):
    ids = strategy["crop_ids"]
    if not ids:
        return 0, [{"label": "No crops", "points": 0}]
    value = sum(VALUE[crops[i]["income"]] for i in ids) / len(ids)
    return _clamp(100 * value), [{"label": "Average income level of the crops (rough, no local prices)",
                                  "points": round(100 * value)}]


def score_passes(crops, strategy, no_till):
    years = max(1, strategy["years"])
    per_year = sum(crops[i]["field_passes_per_year"] for s in strategy["slots"] for i in s["crop_ids"]) / years
    parts = [{"label": f"About {per_year:g} trips across the field each year", "points": round(100 - 10 * (per_year - 1))}]
    if no_till:
        parts.append({"label": "Only crops that can be planted without tilling; check how cover crops are ended", "points": 0})
    return _clamp(100 - 10 * (per_year - 1)), parts


def score(strategy: dict, cal, crops: dict, facts, inputs) -> dict:
    """All six scores, their parts, and the overall score for one set of facts."""
    results = {
        "water": score_water(cal, crops, facts, inputs.irrigation),
        "soil": score_soil(cal, crops, strategy),
        "erosion": score_erosion(cal, crops, facts),
        "forage": score_forage(cal, crops, inputs.livestock),
        "income": score_income(crops, strategy),
        "passes": score_passes(crops, strategy, inputs.no_till),
    }
    doubled = {d for p in inputs.priorities for d in PRIORITY_DIMENSIONS.get(p, ())}
    weights = {d: (2 if d in doubled else 1) for d in DIMENSIONS}
    overall = sum(weights[d] * results[d][0] for d in DIMENSIONS) / sum(weights.values())
    return {
        "scores": {d: results[d][0] for d in DIMENSIONS} | {"overall": _clamp(overall)},
        "parts": {d: results[d][1] for d in DIMENSIONS},
        "weights": weights,
    }


def outlook_overall(base_overall: int, future_risk_count: int) -> int:
    return _clamp(base_overall - FUTURE_RISK_PENALTY * future_risk_count)
