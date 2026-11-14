"""NASA POWER (power.larc.nasa.gov): free NASA satellite and model data for agriculture, no key.

climate()  long-term monthly averages (temperature, rain, root-zone soil moisture, sunlight)
recent()   the last ~30 days of daily data (POWER runs about 2 days behind today)
"""

from datetime import date, timedelta

from .net import get_json

POWER = "https://power.larc.nasa.gov/api/temporal"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MISSING = -999


def climate(lat, lon):
    data = get_json(f"{POWER}/climatology/point", {
        "parameters": "T2M,PRECTOTCORR,GWETROOT,ALLSKY_SFC_SW_DWN",
        "community": "AG", "latitude": round(lat, 4), "longitude": round(lon, 4), "format": "JSON",
    }, timeout=45)
    p = data["properties"]["parameter"]
    return {
        "temp_c": [p["T2M"][m] for m in MONTHS],                     # monthly mean air temperature
        "rain_mm": [round(p["PRECTOTCORR"][m] * 30.4, 1) for m in MONTHS],  # mm/day -> mm/month
        "root_moisture": [p["GWETROOT"][m] for m in MONTHS],          # 0 (dry) to 1 (saturated)
        "sun_kwh": [p["ALLSKY_SFC_SW_DWN"][m] for m in MONTHS],      # kWh/m²/day
        "annual_rain_mm": round(p["PRECTOTCORR"]["ANN"] * 365, 0),
    }


def recent(lat, lon, days=30):
    end = date.today()
    start = end - timedelta(days=days + 5)
    data = get_json(f"{POWER}/daily/point", {
        "parameters": "T2M,T2M_MIN,T2M_MAX,PRECTOTCORR,GWETTOP,GWETROOT",
        "community": "AG", "latitude": round(lat, 4), "longitude": round(lon, 4),
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "format": "JSON",
    }, timeout=45)
    p = data["properties"]["parameter"]
    days_with_data = sorted(d for d, v in p["T2M"].items() if v != MISSING)[-days:]
    if not days_with_data:
        return None

    def series(name):
        return [p[name][d] for d in days_with_data if p[name][d] != MISSING]

    last7 = days_with_data[-7:]
    t_min7 = [p["T2M_MIN"][d] for d in last7 if p["T2M_MIN"][d] != MISSING]
    t_mean7 = [p["T2M"][d] for d in last7 if p["T2M"][d] != MISSING]
    top = series("GWETTOP")
    root = series("GWETROOT")
    return {
        "from": days_with_data[0],
        "to": days_with_data[-1],
        "days": len(days_with_data),
        "rain_mm": round(sum(series("PRECTOTCORR")), 1),
        "temp_c_7day": round(sum(t_mean7) / len(t_mean7), 1) if t_mean7 else None,
        "low_c_7day": round(min(t_min7), 1) if t_min7 else None,
        "high_c_7day": round(max(p["T2M_MAX"][d] for d in last7 if p["T2M_MAX"][d] != MISSING), 1),
        "topsoil_moisture": top[-1] if top else None,
        "root_moisture": root[-1] if root else None,
        "daily": [{"date": d, "temp_c": p["T2M"][d], "rain_mm": p["PRECTOTCORR"][d]} for d in days_with_data],
    }
