# Farmers-Helpers

Type a farm's address. Get NASA climate and soil-moisture data for that exact spot, the USDA soil map, what to plant and when, and local help nearby.

## Run it

Needs Python 3.9+ and nothing else (standard library only).

```bash
echo "SERPAPI_API_KEY=your_key_here" > .env
python3 server.py
```

Open **http://localhost:8000**. `PORT=8080 python3 server.py` changes the port.

## How it works

```
address ──► SerpApi (Google Maps) ──► lat/lon
              │
              ├─► NASA POWER         monthly climate averages + last 30 days of weather & soil moisture
              ├─► USDA Soil Data Access (SoilGrids outside the US)   soil type, pH, texture, organic matter
              ├─► FCC Area API       county & state
              ├─► SerpApi (Google Maps)   nearby extension offices + farm supply stores
              │
              ├─► recommend.py       planting windows per crop, soil + weather advice (with reasons)
              │
              ├─► SerpApi (DuckDuckGo → Google fallback)  the state's university extension planting guides (.edu only)
              └─► SerpApi (Google News)  current farm / drought news for the county, else the state
```

The map uses OpenStreetMap plus three NASA GIBS satellite layers: true-color imagery, plant greenness (MODIS NDVI) and root-zone soil moisture (SMAP).

### SerpApi usage

About 5 searches per new address (geocode, 2 nearby-place searches, guides, news). Every response is cached in `data/cache/` for 6 hours, so repeat lookups cost nothing.

## Files

| Path | What it does |
|---|---|
| `server.py` | Web server: serves `public/` and `GET /api/analyze?address=…` |
| `farmhelper/serp.py` | All SerpApi calls, with caching |
| `farmhelper/nasa.py` | NASA POWER climate and recent daily data |
| `farmhelper/soil.py` | USDA soil survey, with SoilGrids as fallback |
| `farmhelper/recommend.py` | Crop list, planting-window rules, soil and weather advice |
| `farmhelper/analyze.py` | Runs everything in parallel and builds the report |
| `public/` | The website (HTML, CSS, JavaScript with Leaflet and Chart.js) |

Planting windows are rules of thumb from NASA's long-term climate averages, not agronomic advice. The page links each farmer to their state's extension service to confirm.
