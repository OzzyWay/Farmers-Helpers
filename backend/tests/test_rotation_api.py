"""/api/rotation and /api/outlook tests. Every upstream call goes to httpx.MockTransport.

The mock answers like the real services did for Webberwood: NASA POWER daily since 1981,
the Tinn clay soil profile, and Grass/Pasture in 7 of the last 8 crop-map years (2023 shows
Evergreen Forest). The 2030-2049 outlook comes from the precomputed demo-farm file.
"""
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.cache import DiskCache
from app.outlook_store import OutlookStore
from app.services import openmeteo

FX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
TEXT = {
    "trends": (FX / "power_daily_webberwood.json").read_text(encoding="utf-8"),
    "nasa_clim": (FX / "nasa_climatology.json").read_text(encoding="utf-8"),
    "nasa_daily": (FX / "nasa_daily.json").read_text(encoding="utf-8"),
    "soil_profile": (FX / "soil_profile_webberwood.json").read_text(encoding="utf-8"),
    "ssurgo": (FX / "ssurgo_found.json").read_text(encoding="utf-8"),
    "cdl_fault": (FX / "cdl_fault_year.xml").read_text(encoding="utf-8"),
    "om_recent": (FX / "openmeteo_recent_webberwood.json").read_text(encoding="utf-8"),
    "om_future": (FX / "openmeteo_future_webberwood.json").read_text(encoding="utf-8"),
}
FARM = {"lat": "30.233589", "lon": "-97.496006"}
FAR_AWAY = {"lat": "35.2", "lon": "-101.8"}  # Amarillo: no precomputed outlook here


def cdl_xml(category: str) -> str:
    return ('<ns1:GetCDLValueResponse xmlns:ns1="http://cropscape.csiss.gmu.edu/CDLService/"><Result>'
            f'{{x: 1, y: 2, value: 1, category: "{category}", color: "#000000"}}</Result></ns1:GetCDLValueResponse>')


def source_of(request: httpx.Request) -> str:
    host, query = request.url.host, str(request.url.query)
    if "power.larc.nasa.gov" in host:
        if "climatology" in request.url.path:
            return "nasa_clim"
        return "trends" if "EVLAND" in query else "nasa_daily"
    if "sdmdataaccess" in host:
        return "soil_profile" if b"comonth" in request.content else "ssurgo"
    if "nassgeodata" in host:
        return "cdl"
    if "open-meteo" in host:
        return "open_meteo"
    if "giovanni" in host:
        return "giovanni"
    raise AssertionError(f"unexpected host {host}")


# NASA water data (Giovanni): real responses for Webberwood, saved 2026-11-15.
GIOVANNI = {
    "GPM_3IMERGM_07_precipitation": "giovanni_imerg_full.csv",
    "GRACEDADM_CLSM0125US_7D_4_0_gws_inst": "giovanni_grace_gws_full.csv",
    "GRACEDADM_CLSM0125US_7D_4_0_rtzsm_inst": "giovanni_grace_rtzsm_full.csv",
    "GRACEDADM_CLSM0125US_7D_4_0_sfsm_inst": "giovanni_grace_sfsm_full.csv",
}


class Upstream:
    """Mock upstream. `broken` maps a source name to a failure mode."""

    def __init__(self, broken=None):
        self.broken = broken or {}
        self.calls = []

    async def handler(self, request: httpx.Request):
        src = source_of(request)
        self.calls.append(src)
        mode = self.broken.get(src)
        if mode == "timeout":
            raise httpx.ReadTimeout("slow")
        if mode == "http500":
            return httpx.Response(500, text="Internal Server Error")
        if mode == "junk":
            return httpx.Response(200, text="<html>maintenance</html>")
        if mode == "crash":
            raise RuntimeError("unexpected bug in transport")
        if src == "cdl":
            year = int(request.url.params["year"])
            if year >= 2026:
                return httpx.Response(200, text=TEXT["cdl_fault"])
            return httpx.Response(200, text=cdl_xml("Evergreen Forest" if year == 2023 else "Grass/Pasture"))
        if src == "giovanni":
            if request.headers.get("authorization") != "Bearer test-token":
                return httpx.Response(500, json={"message": None})  # how Giovanni rejects a login
            name = GIOVANNI[request.url.params["data"]]
            return httpx.Response(200, text=(FX / name).read_text(encoding="utf-8"))
        if src == "open_meteo":
            start = request.url.params["start_date"]
            return httpx.Response(200, text=TEXT["om_recent"] if start.startswith("1991") else TEXT["om_future"])
        return httpx.Response(200, text=TEXT[src])


@pytest.fixture(autouse=True)
def fake_earthdata_token(monkeypatch):
    """Every test uses a fake token, so the real one in .env is never sent anywhere."""
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-token")


@pytest.fixture
def api(tmp_path):
    """Returns build(upstream) -> TestClient wired to the mock, a temp cache and a temp outlook store."""
    holder = {}

    def build(upstream: Upstream, budget_calls=0):
        def mock_client():
            return httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler))

        async def client_override():
            async with mock_client() as c:
                yield c

        async def no_sleep(_s):
            return None

        cache = DiskCache(tmp_path / "cache")
        budget = openmeteo.Budget(tmp_path / "budget.json")
        if budget_calls:
            budget.spend(budget_calls)
        store = OutlookStore(cache, ROOT / "config" / "outlooks", ROOT / "config" / "demo_farms.json",
                             budget=budget, sleep=no_sleep)
        holder["store"] = store
        main.app.dependency_overrides[main.get_http_client] = client_override
        main.app.dependency_overrides[main.get_cache] = lambda: cache
        main.app.dependency_overrides[main.get_outlook_store] = lambda: store
        main.app.dependency_overrides[main.get_client_factory] = lambda: mock_client
        return TestClient(main.app, raise_server_exceptions=False)

    build.holder = holder
    yield build
    main.app.dependency_overrides.clear()


def get(client, **params):
    return client.get("/api/rotation", params={**FARM, **params})


# ---- the demo farm ----

def test_webberwood_returns_current_plus_alternatives(api):
    r = get(api(Upstream()))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["location"] == {"lat": 30.233589, "lon": -97.496006}
    assert body["missing_sources"] == []
    strategies = body["strategies"]
    assert len(strategies) >= 3
    assert strategies[0]["id"] == "current" and strategies[0]["is_current"]
    assert sum(s["best_fit"] for s in strategies) == 1 and strategies[1]["best_fit"]
    assert body["current_rotation"]["crop_ids"] == ["bermudagrass"]
    assert "7 of 8" in body["current_rotation"]["evidence"]
    assert body["findings"] and body["exclusions"]
    assert "corn" in {e["crop_id"] for e in body["exclusions"]}


def test_response_carries_soil_trends_outlook_and_surface(api):
    body = get(api(Upstream())).json()
    assert body["soil_profile"]["status"] == "ok" and body["soil_profile"]["layers"]
    assert body["soil_facts"]["hydro_group"]["value"] and body["soil_facts"]["flooding"]["value"] == "occasional"
    assert body["ndvi"]["status"] in ("ok", "not_prepared")  # ok once config/ndvi/webberwood.json is built
    away = api(Upstream()).get("/api/rotation", params=FAR_AWAY).json()
    assert away["ndvi"]["status"] == "not_prepared"
    assert body["surface_cover"] == {"value": "Grass/Pasture", "year": "2025", "source": "USDA NASS CDL",
                                     "resolution_m": 30}
    trends = body["trends"]
    assert trends["status"] == "ok" and trends["period"] == "1981-2025"
    hot = next(i for i in trends["indicators"] if i["id"] == "hot_days")
    assert hot["clear"] and hot["per_decade"] > 5
    outlook = body["outlook"]
    assert outlook["status"] == "ok" and outlook["origin"] == "precomputed"
    hot_future = next(i for i in outlook["indicators"] if i["id"] == "hot_days")
    assert hot_future["future_value"]["mid"] > hot["recent_avg"]
    assert body["strategies"][1]["scores"]["outlook"] is not None


def test_response_carries_the_nasa_water_data(api):
    body = get(api(Upstream())).json()
    water = body["water"]
    assert water["status"] == "ok" and water["smap"]["status"] == "unavailable"
    assert water["rain"]["status"] == "ok" and water["rain"]["calendar_vs_power"]["period"] == "2016-2025"
    assert len(water["rain"]["calendar_vs_power"]["imerg_mm"]) == 12
    for part in ("groundwater", "root_zone", "surface"):
        assert water[part]["status"] == "ok" and water[part]["units"] == "percentile"
    assert "test-token" not in json.dumps(body)  # the token never reaches the page


def test_rejected_earthdata_login_keeps_everything_else(api, monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "wrong-token")
    r = get(api(Upstream()))
    assert r.status_code == 200
    body = r.json()
    assert body["water"]["status"] == "unavailable" and "GESDISC" in body["water"]["reason"]
    assert "wrong-token" not in r.text
    assert body["strategies"] and body["trends"]["status"] == "ok"


def test_missing_earthdata_token_is_reported_plainly(api, monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    up = Upstream()
    body = get(api(up)).json()
    assert body["water"]["status"] == "unavailable" and "not set up" in body["water"]["reason"]
    assert "giovanni" not in up.calls  # nothing is requested without a token
    assert body["strategies"]


def test_same_request_gives_the_same_answer(api):
    client = api(Upstream())
    first, second = get(client).json(), get(client).json()
    for key in ("strategies", "exclusions", "findings", "current_rotation"):
        assert json.dumps(first[key], sort_keys=True) == json.dumps(second[key], sort_keys=True), key


def test_second_request_is_served_from_cache(api):
    up = Upstream()
    client = api(up)
    get(client)
    up.calls.clear()
    assert get(client).status_code == 200
    assert up.calls == []


# ---- priorities and constraints ----

def test_priorities_can_rerank_but_never_drop_current(api):
    client = api(Upstream())
    orders = set()
    for priorities in ("", "save_water", "build_soil", "forage", "income", "fewer_passes", "build_soil,forage"):
        body = get(client, priorities=priorities).json()
        assert body["strategies"][0]["id"] == "current"
        assert body["inputs"]["priorities"] == sorted(p for p in priorities.split(",") if p)
        orders.add(tuple(s["id"] for s in body["strategies"]))
    assert len(orders) >= 2  # at least one priority changes the ranking


def test_no_livestock_lists_grazing_options_as_not_suggested(api):
    body = get(api(Upstream()), livestock="no").json()
    assert body["not_suggested"]
    assert all("livestock" in n["reason"] for n in body["not_suggested"])
    ids = {s["id"] for s in body["strategies"]}
    assert not ids & {n["id"] for n in body["not_suggested"]}


def test_irrigation_lifts_the_water_rule(api):
    client = api(Upstream())
    dry = {e["crop_id"] for e in get(client).json()["exclusions"] if e["rule"] == "water"}
    wet = {e["crop_id"] for e in get(client, irrigation="yes").json()["exclusions"] if e["rule"] == "water"}
    assert "corn" in dry and "corn" not in wet


def test_farmer_choice_overrides_the_crop_map(api):
    body = get(api(Upstream()), current="grain_sorghum").json()
    assert body["current_rotation"]["status"] == "farmer_choice"
    assert body["strategies"][0]["crop_ids"] == ["grain_sorghum"]


# ---- bad input ----

@pytest.mark.parametrize("params,fragment", [
    ({"priorities": "save_water,cheap"}, "'cheap'"),
    ({"irrigation": "maybe"}, "'maybe'"),
    ({"livestock": "goats"}, "'goats'"),
    ({"no_till": "sometimes"}, "'sometimes'"),
    ({"current": "pineapple"}, "'pineapple'"),
    ({"lat": "abc"}, "numbers"),
    ({"lat": "48.8566", "lon": "2.3522"}, "only covers US farms"),
])
def test_bad_input_is_400_naming_the_value(api, params, fragment):
    up = Upstream()
    r = api(up).get("/api/rotation", params={**FARM, **params})
    assert r.status_code == 400
    assert fragment in r.json()["detail"]
    assert up.calls == []


def test_missing_location_is_400(api):
    assert api(Upstream()).get("/api/rotation").status_code == 400


# ---- failing sources ----

def test_soil_down_still_200_with_lower_confidence(api):
    # Run the failing case first: the good case would fill the shared temp cache.
    body = get(api(Upstream(broken={"ssurgo": "http500", "soil_profile": "http500"}))).json()
    main.app.dependency_overrides.clear()
    good = get(api(Upstream())).json()  # failures are never cached, so this fetches the soil again
    assert "USDA SSURGO soil" in body["missing_sources"]
    assert "USDA SSURGO soil profile" in body["missing_sources"]
    assert body["soil_profile"]["status"] == "unavailable" and body["soil_profile"]["reason"]
    assert len(body["strategies"]) >= 3
    levels = {"high": 3, "medium": 2, "low": 1}
    assert levels[body["strategies"][1]["confidence"]] < levels[good["strategies"][1]["confidence"]]


def test_trends_down_still_200(api):
    body = get(api(Upstream(broken={"trends": "timeout"}))).json()
    assert body["trends"]["status"] == "unavailable"
    assert "did not respond in time" in body["trends"]["reason"]
    assert "NASA POWER daily climate since 1981" in body["missing_sources"]
    assert len(body["strategies"]) >= 3


@pytest.mark.parametrize("mode", ["timeout", "http500", "junk", "crash"])
def test_never_500_even_when_everything_fails(api, mode):
    up = Upstream(broken={s: mode for s in ("nasa_clim", "nasa_daily", "trends", "ssurgo", "soil_profile", "cdl")})
    r = get(api(up))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_rotation"]["status"] == "unknown"
    assert body["strategies"][0]["id"] == "current"
    assert len(body["missing_sources"]) == 5


def test_outlook_not_loaded_away_from_the_demo_farm(api):
    body = api(Upstream()).get("/api/rotation", params=FAR_AWAY).json()
    assert body["outlook"]["status"] == "not_loaded"
    assert all(s["scores"]["outlook"] is None for s in body["strategies"])


# ---- outlook status and loading ----

def test_outlook_status(api):
    client = api(Upstream())
    assert client.get("/api/outlook", params=FARM).json() == {"status": "ready"}
    assert client.get("/api/outlook", params=FAR_AWAY).json()["status"] == "not_loaded"
    assert client.get("/api/outlook", params={"lat": "x", "lon": "1"}).status_code == 400


def test_outlook_load_ready_for_demo_farm(api):
    up = Upstream()
    r = api(up).post("/api/outlook/load", params=FARM)
    assert r.status_code == 200 and r.json() == {"status": "ready"}
    assert "open_meteo" not in up.calls


def test_outlook_load_runs_in_background_and_then_is_ready(api):
    up = Upstream()
    client = api(up)
    r = client.post("/api/outlook/load", params=FAR_AWAY)
    assert r.status_code == 202 and r.json()["status"] == "loading"
    # TestClient runs background tasks before returning, so the load has finished here.
    assert up.calls.count("open_meteo") == 2
    assert client.get("/api/outlook", params=FAR_AWAY).json() == {"status": "ready"}
    body = client.get("/api/rotation", params=FAR_AWAY).json()
    assert body["outlook"]["status"] == "ok" and body["outlook"]["origin"] == "cached"


def test_outlook_load_refused_when_budget_spent(api):
    up = Upstream()
    r = api(up, budget_calls=4000).post("/api/outlook/load", params=FAR_AWAY)
    assert r.status_code == 200
    assert r.json()["status"] == "unavailable" and "limit" in r.json()["reason"]
    assert "open_meteo" not in up.calls


def test_outlook_load_failure_is_reported_not_500(api):
    up = Upstream(broken={"open_meteo": "http500"})
    client = api(up)
    assert client.post("/api/outlook/load", params=FAR_AWAY).status_code == 202
    status = client.get("/api/outlook", params=FAR_AWAY).json()
    assert status["status"] == "unavailable" and status["reason"]


def test_reserve_marks_loading_before_the_task_starts(tmp_path):
    store = OutlookStore(DiskCache(tmp_path), tmp_path, tmp_path / "none.json")
    store.reserve(35.2, -101.8)
    assert store.status(35.2, -101.8)["status"] == "loading"
