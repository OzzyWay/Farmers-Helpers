"""Why each rotation was suggested, its benefits, risks to check locally, and what we don't know (Req 8).

Every "why" statement cites at least one fact with its value and source. Risks that need a
local check are flagged (local_review) so the page can show them in their own style.
"""
from app.rotation.site_facts import SiteFacts

BASE_GAPS = [
    "No soil test for acidity (pH), phosphorus or potassium.",
    "No local market prices: the income score is a rough guide.",
    "No information about your equipment or labour.",
]
CORE_SOURCES = ("USDA SSURGO soil", "USDA NASS CDL crop history")


def _fact_text(fact, fmt="{:g}"):
    value = fmt.format(fact.value) if isinstance(fact.value, (int, float)) else str(fact.value)
    return f"{value} {fact.units}".strip()


def why(strategy: dict, crops: dict, facts: SiteFacts, current: dict, findings: list[dict]) -> list[dict]:
    """One or two reasons, each with evidence."""
    purpose = strategy["purpose"]
    reasons = []
    if purpose == "current":
        reasons.append({"text": f"This is what the USDA crop map shows on this spot: {current.get('evidence', '')}.",
                        "evidence": [{"value": current.get("evidence"), "units": "", "source": "USDA NASS CDL",
                                      "resolution_m": 30, "period": ""}]})
        return reasons
    if facts.hot_days and purpose in ("forage", "erosion_water", "income"):
        reasons.append({"text": f"Built around heat- and drought-tolerant crops for a field with about "
                                f"{_fact_text(facts.hot_days, '{:.0f}')} above 35 °C in recent years.",
                        "evidence": [facts.hot_days.cite()]})
    if purpose in ("soil", "cover"):
        added = [s for s in strategy["slots"] if not s["fixed"]]
        legumes = [crops[c]["name"] for s in added for c in s["crop_ids"] if crops[c]["nitrogen_fixing"]]
        text = "Adds living roots in a season with no crop growing today"
        if legumes:
            text += f", and {', '.join(legumes)} adds nitrogen from the air"
        if facts.om_pct:
            text += f". The surface soil is {_fact_text(facts.om_pct)} plant and animal material"
        reasons.append({"text": text + ".", "evidence": [facts.om_pct.cite()] if facts.om_pct else []})
    if purpose == "erosion_water" and (facts.hydro_group or facts.flooding):
        f = facts.hydro_group or facts.flooding
        reasons.append({"text": f"A deep-rooted perennial keeps the soil covered all year where rain soaks in "
                                f"slowly (soil group {facts.hydro_group.value if facts.hydro_group else 'unknown'}).",
                        "evidence": [f.cite()]})
    if purpose == "income" and facts.rain_total:
        reasons.append({"text": f"Uses grain crops that need less water than corn; this field averaged "
                                f"{_fact_text(facts.rain_total, '{:.0f}')} of rain recently.",
                        "evidence": [facts.rain_total.cite()]})
    # Always tie in the strongest finding when nothing else cited a fact.
    if not any(r["evidence"] for r in reasons) and findings:
        f = findings[0]
        reasons.append({"text": f"Responds to: {f['title'].lower()}. {f['text']}", "evidence": f["evidence"]})
    return [r for r in reasons if r["evidence"]] or reasons


def benefits(strategy: dict, crops: dict, inputs) -> list[str]:
    ids = strategy["crop_ids"]
    out = []
    legumes = [crops[i]["name"] for i in ids if crops[i]["nitrogen_fixing"]]
    if legumes:
        out.append(f"{', '.join(legumes)} add nitrogen, a plant nutrient, so the next crop may need less fertilizer.")
    deep = [crops[i]["name"] for i in ids if crops[i]["root_depth"] == "deep"]
    if deep:
        out.append(f"Deep roots ({', '.join(deep)}) reach water lower down and open channels for rain to soak in.")
    covers = [crops[i]["name"] for i in ids if crops[i]["erosion_protection"] == "high"]
    if covers:
        out.append(f"Strong soil cover from {', '.join(covers)} protects against erosion.")
    if inputs.livestock != "no":
        forage = [crops[i]["name"] for i in ids if crops[i]["forage_value"] == "high"]
        if forage:
            out.append(f"Good grazing or hay from {', '.join(forage)}.")
    tough = [crops[i]["name"] for i in ids if crops[i]["drought_tolerance"] == "high"]
    if tough:
        out.append(f"Handles dry spells well: {', '.join(tough)}.")
    return out or ["Keeps your current system, with no change in equipment or markets."]


def risks(strategy: dict, crops: dict, facts: SiteFacts) -> list[dict]:
    out = [{"text": f"{crops[i]['name']}: {r}", "local_review": True} for i in strategy["crop_ids"] for r in crops[i]["risks"]]
    group = str(facts.hydro_group.value) if facts.hydro_group else ""
    if group.startswith("D"):
        out.append({"text": "Rain soaks in slowly (soil group D), so heavy rain runs off. Plan planting and grazing around wet spells.",
                    "local_review": True})
    added = [s for s in strategy["slots"] if not s["fixed"] and s["role"] == "winter"]
    if added:
        out.append({"text": "Ask your county extension agent how much seed to use and when to end the cover crop.",
                    "local_review": True})
    return out or [{"text": "Check this plan with your county extension agent.", "local_review": True}]


def gaps(missing_sources) -> list[str]:
    return BASE_GAPS + [f"Missing data: {name}." for name in missing_sources]


def soil_health_notes(strategy: dict, crops: dict) -> list[dict]:
    """One sentence for each legume, cover, deep-rooted or drought-tolerant crop (Req 8.5)."""
    out = []
    for i in strategy["crop_ids"]:
        crop = crops[i]
        if (crop["nitrogen_fixing"] or crop["category"] in ("legume_cover", "summer_legume_cover", "cereal_cover")
                or crop["root_depth"] == "deep" or crop["drought_tolerance"] == "high"):
            out.append({"crop_id": i, "crop_name": crop["name"], "text": crop["soil_note"]})
    return out


def confidence(missing_sources, outlook_loaded: bool, current: dict) -> tuple[str, list[str]]:
    """high / medium / low, plus the missing facts that lowered it (Req 8.6)."""
    missing = list(missing_sources)
    if not outlook_loaded:
        missing.append("2030-2049 climate outlook (not loaded)")
    if any(m in CORE_SOURCES for m in missing_sources) or current.get("status") == "unknown":
        return "low", missing
    if missing:
        return "medium", missing
    return "high", []
