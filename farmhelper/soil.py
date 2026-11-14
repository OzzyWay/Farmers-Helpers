"""Soil at a point.

US:      USDA NRCS Soil Data Access (SSURGO soil survey): the mapped soil and its top layer.
Fallback: ISRIC SoilGrids (global, modeled) when USDA has no data (outside the US, cities, water).
"""

from .net import FetchError, get_json, post_json

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"


def texture_class(sand, silt, clay):
    """USDA soil texture triangle (percentages)."""
    if None in (sand, silt, clay):
        return None
    if clay >= 40:
        return "Silty clay" if silt >= 40 else ("Clay" if sand <= 45 else "Sandy clay")
    if clay >= 35 and sand > 45:
        return "Sandy clay"
    if clay >= 27:
        if sand <= 20:
            return "Silty clay loam"
        return "Clay loam" if sand <= 45 else "Sandy clay loam"
    if clay >= 20 and sand > 45 and silt < 28:
        return "Sandy clay loam"
    if silt >= 80 and clay < 12:
        return "Silt"
    if silt >= 50:
        return "Silt loam"
    if sand >= 85 and silt + 1.5 * clay < 15:
        return "Sand"
    if sand >= 70 and silt + 2 * clay < 30:
        return "Loamy sand"
    if sand > 52 or (clay < 7 and silt < 50):
        return "Sandy loam"
    return "Loam"


def _usda(lat, lon):
    query = f"""
        SELECT TOP 1 mu.muname, c.compname, c.comppct_r, c.drainagecl,
               h.ph1to1h2o_r, h.sandtotal_r, h.silttotal_r, h.claytotal_r, h.om_r, h.awc_r
        FROM mapunit mu
        JOIN component c ON c.mukey = mu.mukey
        JOIN chorizon h ON h.cokey = c.cokey
        WHERE mu.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('point({lon:.6f} {lat:.6f})'))
        ORDER BY c.comppct_r DESC, h.hzdept_r ASC"""
    rows = post_json(SDA_URL, {"query": query, "format": "JSON+COLUMNNAME"}).get("Table") or []
    if len(rows) < 2:
        return None
    rec = dict(zip(rows[0], rows[1]))

    def num(k):
        return float(rec[k]) if rec.get(k) not in (None, "") else None

    sand, silt, clay = num("sandtotal_r"), num("silttotal_r"), num("claytotal_r")
    if num("ph1to1h2o_r") is None and clay is None:
        return {"source": "USDA soil survey", "name": rec["muname"], "note": "No farm soil data here (built-up land or water)."}
    return {
        "source": "USDA NRCS soil survey (SSURGO)",
        "name": rec["muname"],
        "series": rec["compname"],
        "drainage": rec.get("drainagecl"),
        "ph": num("ph1to1h2o_r"),
        "sand": sand, "silt": silt, "clay": clay,
        "organic_matter": num("om_r"),
        "water_capacity": num("awc_r"),  # inches of water per inch of soil
        "texture": texture_class(sand, silt, clay),
    }


def _soilgrids(lat, lon):
    params = [("lon", round(lon, 4)), ("lat", round(lat, 4))]
    params += [("property", p) for p in ("phh2o", "clay", "sand", "silt", "soc")]
    params += [("depth", "0-5cm"), ("value", "mean")]
    from urllib.parse import urlencode
    data = get_json(f"{SOILGRIDS_URL}?{urlencode(params)}", timeout=45)
    vals = {}
    for layer in data["properties"]["layers"]:
        v = layer["depths"][0]["values"]["mean"]
        vals[layer["name"]] = None if v is None else v / layer["unit_measure"]["d_factor"]
    if vals.get("phh2o") is None:
        return None
    pct = lambda gkg: None if gkg is None else round(gkg / 10, 1)  # g/kg -> %
    sand, silt, clay = pct(vals.get("sand")), pct(vals.get("silt")), pct(vals.get("clay"))
    soc = vals.get("soc")  # g/kg of organic carbon
    return {
        "source": "ISRIC SoilGrids (global soil model)",
        "name": f"{texture_class(sand, silt, clay) or 'Soil'} (modeled)",
        "ph": round(vals["phh2o"], 1),
        "sand": sand, "silt": silt, "clay": clay,
        "organic_matter": None if soc is None else round(soc / 10 * 1.72, 1),  # organic carbon -> organic matter %
        "texture": texture_class(sand, silt, clay),
    }


def soil_at(lat, lon):
    usda = None
    try:
        usda = _usda(lat, lon)
    except FetchError:
        pass
    if usda and usda.get("ph") is not None:
        return usda
    try:
        modeled = _soilgrids(lat, lon)
    except FetchError:
        modeled = None
    if modeled:
        if usda:
            modeled["note"] = f"USDA maps this spot as \"{usda['name']}\"; showing nearby modeled soil instead."
        return modeled
    return usda or {"source": None, "name": "Unknown", "note": "No soil data found for this location."}
