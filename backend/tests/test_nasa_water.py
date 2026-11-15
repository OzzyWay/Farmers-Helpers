"""NASA satellite water data tests (Req 23.12): parsing, monthly aggregation, trend, the
low-groundwater finding, a missing or rejected token, a timeout, and the monthly cache.

The fixtures giovanni_*_full.csv are real Giovanni Time Series answers for Webberwood
(2026-11-15). No test touches the network, and no test uses the real token.
"""
import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.cache import DiskCache
from app.rotation_data import apply_water
from app.services import nasa_water
from app.services.base import SourceUnavailable

FX = Path(__file__).parent / "fixtures"
LAT, LON = 30.233589, -97.496006
TODAY = date(2026, 11, 15)
FILES = {
    "GPM_3IMERGM_07_precipitation": "giovanni_imerg_full.csv",
    "GRACEDADM_CLSM0125US_7D_4_0_gws_inst": "giovanni_grace_gws_full.csv",
    "GRACEDADM_CLSM0125US_7D_4_0_rtzsm_inst": "giovanni_grace_rtzsm_full.csv",
    "GRACEDADM_CLSM0125US_7D_4_0_sfsm_inst": "giovanni_grace_sfsm_full.csv",
}


def text(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


# ---- parsing ----

def test_parse_real_imerg_csv():
    meta, rows = nasa_water.parse_csv(text("giovanni_imerg_full.csv"))
    assert meta["prod_name"] == "GPM_3IMERGM.07" and meta["unit"] == "mm/hr"
    assert rows[0] == ("2000-06-01 00:00", 0.166)
    assert len(rows) == 304


def test_parse_drops_the_fill_value_and_stray_lines():
    csv = ("prod_name,X\nundef,-999\n\nTimestamp (UTC),Data\n"
           "2024-01-01 00:00,12.5\n2024-01-08 00:00,-999\nnot a row\n2024-01-15 00:00,14\n")
    _, rows = nasa_water.parse_csv(csv)
    assert rows == [("2024-01-01 00:00", 12.5), ("2024-01-15 00:00", 14.0)]


@pytest.mark.parametrize("junk", ["", "<html>maintenance</html>", '{"message":null}'])
def test_parse_rejects_anything_that_is_not_a_time_series(junk):
    with pytest.raises(SourceUnavailable, match="could not read"):
        nasa_water.parse_csv(junk)


# ---- rain ----

def test_rain_turns_mm_per_hour_into_mm_per_month():
    meta, rows = nasa_water.parse_csv(text("giovanni_imerg_monthly.csv"))  # 2023 only
    rain = nasa_water.rain_summary(meta, rows, "IMERG", 11000)
    jan = rain["monthly"][0]
    assert jan == {"month": "2023-01", "rain_mm": round(0.064 * 24 * 31, 1)}  # 47.6 mm
    assert rain["yearly"][0][0] == 2023 and rain["yearly"][0][1] == pytest.approx(
        sum(m["rain_mm"] for m in rain["monthly"]), abs=0.2)
    assert rain["trend"]["method"] == "not_enough_years"  # one year is not a trend


def test_rain_summary_of_the_full_record():
    meta, rows = nasa_water.parse_csv(text("giovanni_imerg_full.csv"))
    rain = nasa_water.rain_summary(meta, rows, "IMERG", 11000)
    years = [y for y, _ in rain["yearly"]]
    assert years[0] == 2001 and years[-1] == 2024  # 2000 starts in June, 2025 ends in September
    assert rain["trend"]["n_years"] == 24 and rain["trend"]["method"] == "theil_sen"
    assert 500 < rain["recent_avg"] < 1300  # Central Texas: roughly 700-1000 mm a year
    assert len(rain["calendar"]) == 12 and all(v is not None for v in rain["calendar"])
    assert rain["grid_point"] == {"lat": 30.25, "lon": -97.45}


def test_calendar_average_leaves_gaps_instead_of_zeros():
    monthly = [{"month": "2024-01", "rain_mm": 10.0}, {"month": "2025-01", "rain_mm": 30.0}]
    avg = nasa_water.calendar_average(monthly, 2024, 2025)
    assert avg[0] == 20.0 and avg[1:] == [None] * 11


# ---- GRACE percentiles and the finding ----

def test_percentiles_by_month_latest_and_last_year():
    meta, rows = nasa_water.parse_csv(text("giovanni_grace_gws_full.csv"))
    gw = nasa_water.percentile_summary(meta, rows, "GRACE-DA", 14000)
    assert gw["latest"] == {"date": "2026-08-31", "pct": 19.2}
    assert gw["monthly"][0]["month"] == "2003-01"
    assert 0 <= gw["last_12m_avg"] <= 100
    assert gw["last_12m_period"] == "2025-08-31 to 2026-08-31"


def test_groundwater_finding_only_below_20():
    low = {"groundwater": {"status": "ok", "last_12m_avg": 14.6, "source": "GRACE-DA",
                           "resolution_m": 14000, "last_12m_period": "2025-08-31 to 2026-08-31"}}
    f = nasa_water.groundwater_finding(low)
    assert f["id"] == "low_groundwater" and "averaged 15 on the 0-100 percentile scale" in f["text"]
    assert f["evidence"][0]["value"] == 14.6 and f["evidence"][0]["source"] == "GRACE-DA"
    assert nasa_water.groundwater_finding({"groundwater": dict(low["groundwater"], last_12m_avg=20)}) is None
    assert nasa_water.groundwater_finding({"groundwater": {"status": "unavailable"}}) is None
    assert nasa_water.groundwater_finding({}) is None


def test_apply_water_adds_the_power_comparison_and_the_finding():
    water = {"status": "ok",
             "rain": {"status": "ok", "monthly": [{"month": "2020-05", "rain_mm": 100.0}]},
             "groundwater": {"status": "ok", "last_12m_avg": 10.0, "source": "GRACE-DA"}}
    result = {"findings": [{"id": "rising_heat"}]}
    trends = {"monthly": {"period": "2016-2025", "rain_mm": [1.0] * 12}}
    apply_water(result, water, trends)
    cmp = water["rain"]["calendar_vs_power"]
    assert cmp["period"] == "2016-2025" and cmp["imerg_mm"][4] == 100.0 and cmp["power_mm"] == [1.0] * 12
    assert [f["id"] for f in result["findings"]] == ["rising_heat", "low_groundwater"]
    unchanged = {"findings": []}
    apply_water(unchanged, {"status": "unavailable"}, trends)
    assert unchanged == {"findings": []}


# ---- fetching ----

class FakeGiovanni:
    def __init__(self, mode=None, token="test-token"):
        self.mode, self.token, self.calls = mode, token, []

    async def handler(self, request: httpx.Request):
        var = request.url.params["data"]
        self.calls.append(var)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("slow")
        if self.mode == "grace_down" and var.startswith("GRACE"):
            return httpx.Response(503, text="Service Unavailable")
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(500, json={"message": None})
        return httpx.Response(200, text=text(FILES[var]))


def run_fetch(fake, tmp_path, token="test-token", today=TODAY):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as c:
            return await nasa_water.fetch(c, LAT, LON, DiskCache(tmp_path), token=token, today=today)
    return asyncio.run(go())


def test_fetch_gets_all_four_parts_and_caches_them(tmp_path):
    fake = FakeGiovanni()
    doc = run_fetch(fake, tmp_path)
    assert doc["status"] == "ok" and doc["live_or_cached"] == "live"
    assert all(doc[p]["status"] == "ok" for p in nasa_water.PARTS)
    assert len(fake.calls) == 4
    again = run_fetch(fake, tmp_path)
    assert again["live_or_cached"] == "cached" and len(fake.calls) == 4  # no new request
    cached_file = next(tmp_path.glob("nasa_water_2026-11_*.json")).read_text(encoding="utf-8")
    assert "test-token" not in cached_file  # the token is never written to the cache


def test_a_new_month_fetches_again(tmp_path):
    fake = FakeGiovanni()
    run_fetch(fake, tmp_path, today=date(2026, 11, 15))
    run_fetch(fake, tmp_path, today=date(2026, 12, 1))
    assert len(fake.calls) == 8


def test_missing_token_asks_nothing(tmp_path):
    fake = FakeGiovanni()
    doc = run_fetch(fake, tmp_path, token="")
    assert doc["status"] == "unavailable" and "not set up" in doc["reason"] and fake.calls == []


def test_rejected_token_is_explained_and_not_cached(tmp_path):
    fake = FakeGiovanni(token="the-right-one")
    doc = run_fetch(fake, tmp_path, token="wrong")
    assert doc["status"] == "unavailable" and "GESDISC DATA ARCHIVE" in doc["reason"]
    assert "wrong" not in str(doc)
    assert not list(tmp_path.glob("nasa_water_*"))


def test_timeout_is_reported_plainly(tmp_path):
    doc = run_fetch(FakeGiovanni(mode="timeout"), tmp_path)
    assert doc["status"] == "unavailable" and "did not respond in time" in doc["reason"]


def test_one_failing_part_keeps_the_others_and_is_not_cached(tmp_path):
    doc = run_fetch(FakeGiovanni(mode="grace_down"), tmp_path)
    assert doc["status"] == "ok" and doc["rain"]["status"] == "ok"
    assert doc["groundwater"]["status"] == "unavailable" and "503" in doc["groundwater"]["reason"]
    assert not list(tmp_path.glob("nasa_water_*"))  # incomplete results are not cached
