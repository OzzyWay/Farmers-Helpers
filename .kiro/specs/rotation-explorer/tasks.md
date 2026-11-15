# Implementation Plan

Phase 1 (tasks 1–16) is the hackathon deadline. Phase 2 (tasks 17–21) waits until after it. Each task builds on the ones before it. Do not read `.env` values into code, logs or responses, and add no new backend or frontend packages.

Order changed on 2026-11-15 after a review: the engine and API first (7–9), then NASA satellite data (10 MODIS NDVI, 11 IMERG / GRACE / SMAP), then the frontend (12–14), then checks (15–16).

## Phase 1

- [x] 1. Trim fixtures and set up the rotation package
  - [x] 1.1 Reduce `backend/tests/fixtures/raw_probe/` to small fixtures:
    - POWER daily: keep 1981–2025, but only the 5 variables, rounded to 2 decimals.
    - Open-Meteo: keep both periods as they are (about 1 MB together).
    - Rename the files to `power_daily_webberwood.json`, `openmeteo_recent_webberwood.json` and `openmeteo_future_webberwood.json`.
    - _Requirements: 14.1_
  - [x] 1.2 Create `backend/app/rotation/__init__.py` with a module docstring, and `rotation/site_facts.py` with the `Fact`, `SiteFacts` and `FarmInputs` dataclasses
    - _Requirements: 16.4_

- [x] 2. Crop table
  - [x] 2.1 Write `config/crops.json` with the 15 crops from Req 5.1 and every attribute from Req 5.2 and the design
    - Use SARE *Managing Cover Crops Profitably*, USDA NRCS Plant Guides and Texas A&M AgriLife Extension.
    - Give each crop at least one source with a title and a URL. Fetch each URL to check it loads before committing it.
    - Add the `_comment` stating the values were written for Central Texas.
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [x] 2.2 Implement `rotation/crops.py`: load and validate at startup
    - Check required keys, enum values, months 1–12, and at least one http(s) source.
    - On a bad file, stop the app with a message naming the crop and the field.
    - _Requirements: 5.5_
  - [x] 2.3 Write `test_crops_table.py`: the real file passes; a missing attribute, a missing source and a bad enum each fail with a useful message
    - _Requirements: 14.6_

- [x] 3. Soil profile service
  - [x] 3.1 Save live Soil Data Access responses as fixtures: all horizons of the dominant component, and the `comonth` flooding and ponding query, for Webberwood and one empty point
    - _Requirements: 14.1_
  - [x] 3.2 Implement `services/soil_profile.py`
    - Layers sorted by depth; per-layer properties omitted when missing.
    - Flooding and ponding use the most frequent class across months.
    - "No soil survey data for this location" when empty; Disk_Cache key `soil_profile`.
    - _Requirements: 2.1–2.7_
  - [x] 3.3 Write `test_soil_profile.py`: success, missing property, empty result, timeout, HTTP error, malformed response, cache hit
    - _Requirements: 14.1_

- [x] 4. Climate indicators and trends
  - [x] 4.1 Implement `rotation/indicators.py`
    - Pure functions for the 11 indicators in the design table.
    - Skip years with more than 10% of days missing.
    - The heavy-rain threshold is the 95th percentile of wet days in 1981–2010.
    - _Requirements: 17.2, 17.3_
  - [x] 4.2 Implement `rotation/trends.py`
    - Theil–Sen slope per decade and the tie-corrected two-sided Mann–Kendall p-value.
    - `clear` when p < 0.05; first-decade and last-decade averages.
    - The rare-event path (zeros in more than half the years) compares the first 15 and last 15 years.
    - _Requirements: 17.4, 17.5, 17.7, 17.12_
  - [x] 4.3 Implement `services/climate_trends.py`
    - One NASA POWER daily request for `T2M_MIN,T2M_MAX,PRECTOTCORR,GWETROOT,EVLAND` from 1981 to the last complete year.
    - Cache the computed indicators (not the raw data) under a key that includes the last complete year.
    - Return "unavailable" with a reason on failure.
    - _Requirements: 17.1, 17.10, 17.11_
  - [x] 4.4 Write `test_rotation_indicators.py` and `test_rotation_trends.py`
    - Hand-made daily series for each indicator, including a leap year, missing days and frost-date edges.
    - Trend tests: a known slope within 5%, flat noise not clear, one extreme year, missing years, the rare-event path, and a hand-computed Mann–Kendall value.
    - A check against the Webberwood fixture: about +10 hot days per decade, clear.
    - _Requirements: 14.9, 14.10_

- [x] 5. Open-Meteo outlook
  - [x] 5.1 Implement `services/openmeteo.py`
    - Two requests (1991–2020, then 2030–2049) for 3 models and 3 variables, at least 65 s apart.
    - Estimate the weight with `days / 14 × max(1, variables / 10) × models`.
    - The budget guard stores hourly and daily counts in `backend/cache/openmeteo_budget.json` and refuses loads above 4,500 an hour or 9,000 a day.
    - A 429 maps to "unavailable" with a plain reason.
    - _Requirements: 18.1, 18.9, 18.10_
  - [x] 5.2 Compute the outlook
    - Per-model change = future average − recent average; low, middle and high across models.
    - Future value = POWER 1991–2020 observed + change (the delta method).
    - _Requirements: 18.2, 18.3_
  - [x] 5.3 Implement `outlook_store.py`
    - Lookup order: the precomputed demo-farm file, then the cache by 0.1° cell (30 days), then "not loaded".
    - One background load at a time, with an in-memory status.
    - _Requirements: 18.1, 18.8, 18.12_
  - [x] 5.4 Write `backend/scripts/build_outlook.py`, and run it once to create `config/outlooks/webberwood.json` with the models, periods, fetch date and licence recorded
    - _Requirements: 18.1, 18.11_
  - [x] 5.5 Write `test_outlook.py`: the delta method on the fixtures, the weight estimate, the budget guard refusing work, 429 handling, the precomputed lookup, and cache expiry
    - _Requirements: 14.1_

- [x] 6. Current rotation
  - [x] 6.1 Implement `rotation/current.py`
    - Map CDL categories to crop ids.
    - Continuous when one category appears in at least 6 years; alternating otherwise.
    - "Unknown" when more than half the years are not farmland.
    - A farmer override comes from the `current` parameter.
    - _Requirements: 6.1–6.6_
  - [x] 6.2 Write tests covering: Webberwood (pasture 7 of 8), corn–soybean alternation, mostly forest (unknown), empty history, override
    - _Requirements: 14.1_

- [x] 7. Rules, templates, scoring, findings, explanations
  - [x] 7.1 Implement `rotation/site_facts.py` builders: `SiteFacts` for today from the farm-data records, the soil profile and the trends summary, and for the outlook from the delta-method future values
    - Parse the slope range text ("0 to 1") into a number (the top of the range) for the erosion rule.
    - _Requirements: 4.3, 18.6_
  - [x] 7.2 Implement `rotation/rules.py`: the wet-soil, heat, frost, water and livestock rules for "today" and "outlook", with plain reasons
    - _Requirements: 7.3, 7.4, 7.8, 18.7_
  - [x] 7.3 Implement `rotation/templates.py`
    - The 5 templates with slots and candidates.
    - Fill each slot with the first non-excluded candidate.
    - Check the back-to-back pest-family rule and the in-season months rule.
    - _Requirements: 7.2, 7.6, 7.7_
  - [x] 7.4 Implement `rotation/scoring.py`
    - The six dimensions with returned score parts.
    - Overall weighted mean with priority dimensions doubled.
    - Outlook score with the future-risk penalty.
    - Deterministic tie-breaking.
    - _Requirements: 10.1–10.5, 18.6_
  - [x] 7.5 Implement `rotation/findings.py`: the finding rules in priority order, keeping up to 6, each with cited evidence (includes the root-zone soil wetness and water balance trends from NASA POWER)
    - _Requirements: 4.1–4.6, 17.9_
  - [x] 7.6 Implement `rotation/explain.py`
    - Why, benefits, risks (local-review flag), gaps, soil-health notes, confidence with missing facts.
    - The calendar per strategy: crop, bare, heat, frost and wettest flags for each month.
    - _Requirements: 8.1–8.7, 11.1–11.4, 12.4_
  - [x] 7.7 Implement `rotation/engine.py`
    - Pure orchestration with no I/O.
    - Returns the current strategy plus the best 3 fillable alternatives (at least 2 guaranteed by the fallback templates), exclusions and findings.
    - _Requirements: 7.1, 9.4, 9.7_
  - [x] 7.8 Write `test_rotation_rules.py` and `test_rotation_engine.py`
    - Each rule fires and doesn't fire.
    - The future-risk case.
    - The engine tests use Webberwood and 3 synthetic sites: dry west Texas, wet sandy East Texas, Iowa row crops. They cover correctness properties 1–7 and priority re-ranking.
    - _Requirements: 14.2, 14.4, 14.5, 14.7, 14.11_

- [x] 8. Rotation and outlook API
  - [x] 8.1 Add `GET /api/rotation` to `main.py`
    - Validate the location and every parameter value (400, naming the bad value).
    - Gather farm-data, the soil profile, trends and the outlook (precomputed or cached) concurrently, build `SiteFacts` and run the engine.
    - Return the trends summary, the soil profile and the outlook in the response, so the frontend can draw them.
    - Always 200 once the input is valid, with `missing_sources` listed.
    - _Requirements: 13.1–13.5_
  - [x] 8.2 Add `GET /api/outlook` (status) and `POST /api/outlook/load` (start the background load if the budget allows)
    - Neither may return a 500.
    - _Requirements: 18.1, 18.10, 18.12_
  - [x] 8.3 Write `test_rotation_api.py`
    - Webberwood fixtures give at least 3 strategies including the current one.
    - 400 cases; a source failure still gives 200 with lower confidence.
    - Determinism across repeated calls.
    - A priority change can re-rank but never removes the current strategy.
    - _Requirements: 14.3, 14.4, 14.5_
  - [x] 8.4 Checkpoint: run `backend/run_tests.py` and fix all failures

- [x] 9. Verify script
  - [x] 9.1 Extend `backend/verify.py` with a live `/api/rotation` check for the demo farm (temporary cache)
    - Report the counts of findings, strategies and exclusions, and the trends and outlook status.
    - _Requirements: 14.8_

- [ ] 10. MODIS NDVI (NASA satellite, no login)
  - Decision 2026-11-15 (option b): last 3 complete years, prepared for demo farms by `scripts/build_ndvi.py` into `config/ndvi/<farm>.json`; `app/ndvi_store.py` looks it up.
  - [x] 10.1 Probe the ORNL DAAC MODIS web service for Webberwood: the MOD13Q1 (and MYD13Q1) date list, one subset request, speed, size and limits. Save the responses as fixtures.
  - Status 2026-11-15: 10.2–10.4 are built in the reduced "option b" form (3 complete years, precomputed per demo farm instead of 10 years fetched live with a monthly cache). Other addresses show "satellite data prepared for demo farms only".
  - [x] 10.2 Implement `services/ndvi.py`: fetch the 16-day 250 m NDVI series for at least the last 10 complete years, apply the quality flags, compute the typical NDVI and the bare-soil share per month with a documented threshold, and cache monthly
    - _Requirements: 21.1, 21.2, 21.6_
  - [x] 10.3 Use the satellite bare months in the current rotation's calendar and in a "bare soil" finding, and add NDVI to `/api/rotation`
    - _Requirements: 21.3, 4.5_
  - [x] 10.4 Write `test_ndvi.py`: parsing, quality filtering, monthly aggregation, bare-month rule, failure handling, cache
    - _Requirements: 14.1_

- [x] 11. NASA water data: IMERG, GRACE and SMAP (needs `EARTHDATA_TOKEN`)
  - [x] 11.1 With the token set in `.env`, probe the GES DISC Giovanni Time Series API for Webberwood: `GPM_3IMERGM_07_precipitation`, `GRACEDADM_CLSM0125US_7D_4_0_gws_inst`, `GRACEDADM_CLSM0125US_7D_4_0_rtzsm_inst`. Save the responses as fixtures.
    - Done 2026-11-15 (`scripts/probe_nasa_water.py`): all three answer HTTP 200 as CSV in about 2 s (metadata lines, a blank line, then `Timestamp (UTC),Data`). IMERG monthly is in mm/hr on a 0.1° grid; GRACE-DA US is weekly percentiles (%) on a 0.125° grid. Fixtures: `tests/fixtures/giovanni_imerg_monthly.csv`, `giovanni_grace_gws.csv`, `giovanni_grace_rtzsm.csv`. Needs the "NASA GESDISC DATA ARCHIVE" app approved in Earthdata Login (without it the service answers HTTP 500 `{"message":null}` and GES DISC files answer 401).
  - [x] 11.2 Probe SMAP through NASA AppEEARS (point sample of SPL3SMP_E or SPL4SMGP) with the same token; if it is rejected, record why and mark SMAP unavailable
    - Decision 2026-11-15 (user): not probed for the deadline. AppEEARS answers asynchronously (minutes), too slow for a live page. SMAP is reported as "planned for a later version" (Req 23.3's unavailable path); GRACE root-zone and surface soil moisture cover soil wetness. Moved to Phase 2.
  - [x] 11.3 Implement `services/nasa_water.py`: authenticated requests (token never logged or cached), monthly IMERG rain with trend, GRACE groundwater and root-zone percentiles, SMAP where reachable, monthly cache
    - _Requirements: 23.1–23.6, 23.11_
    - Live for Webberwood on 2026-11-15: all four series in about 2.5 s in parallel; GRACE surface soil moisture added too.
  - [x] 11.4 Add the groundwater finding, and add the water data to `/api/rotation`
    - _Requirements: 23.9_
  - [x] 11.5 Write `test_nasa_water.py`: parsing, aggregation, trend, finding, missing token, rejected token, timeout
    - _Requirements: 23.12_

Note (2026-11-15): at the team's request the frontend (12, 14) was built before tasks 10-11, so the
rotation comparison is visible for the demo. Tasks 10, 11 and 14.2 remain.
Later team update: the 3D soil block now lives in the farm-data panel's Soil tab (compact mode,
with a layer list), fed by the /api/rotation answer through App.jsx; it is no longer in the summary.

- [x] 12. Page layout and map scrolling
  - [x] 12.1 Make the page scroll
    - The map section is `100vh` with the existing top bar and panel unchanged.
    - `FieldSummary` follows it.
    - A "Your field summary ↓" pill button scrolls down (smoothly unless reduced motion is on).
    - _Requirements: 1.1, 1.2, 1.5, 1.6_
  - [x] 12.2 Set `cooperativeGestures: true` in `TerrainMap.jsx`, with the hint text set through the MapLibre `locale` option
    - Confirm the option names with Context7 for MapLibre v5.
    - _Requirements: 1.3, 1.4, 1.7_
  - [x] 12.3 Create `fieldSummary/useRotation.js` and `fieldSummary/useOutlook.js`
    - `useRotation`: abort stale requests, retry, 300 ms debounce on priority changes, `localStorage` for priorities.
    - `useOutlook`: status, load, and polling every 10 s.
    - _Requirements: 9.3, 9.5, 9.6, 13.6, 18.12_

- [x] 13. 3D soil block
  - [x] 13.1 Create `fieldSummary/soilColors.js`: texture group → colour and pattern, with contrast checked against both themes
    - _Requirements: 3.2, 15.2_
  - [x] 13.2 Create `fieldSummary/SoilBlock.jsx`
    - A CSS 3D cuboid with layer bands in proportion to depth, the CDL surface on top, a cm and inch scale, and the runoff and slow-drainage indicators.
    - Rotate by pointer drag and by Left/Right arrows in 15° steps.
    - The idle rotation runs only without reduced motion.
    - A text-alternative table, and an explanation when no profile is available.
    - _Requirements: 3.1–3.11_

- [ ] 14. Summary sections
  - [x] 14.1 Create `ClimateTrends.jsx` (the Load button and wait message live in FieldSummary's outlook note)
    - One Recharts chart per indicator: yearly points, trend line, decade averages, outlook band.
    - A plain "per decade" sentence and the clear / "no clear change" chip.
    - A hidden data table, the outlook source and Open-Meteo CC BY 4.0 credit, and the "Load 2030–2049 outlook" button with the wait message.
    - _Requirements: 17.6–17.8, 18.4, 18.5, 18.11, 18.12_
  - [x] 14.2 (NDVI in `SatelliteData.jsx`; water data in `WaterData.jsx`, checked live in the browser 2026-11-15) Create `SatelliteData.jsx`: the NDVI chart with bare months, IMERG rain next to POWER rain, GRACE groundwater and soil moisture percentiles, SMAP when available, each with its resolution and a plain "satellite vs model" note
    - _Requirements: 21.4, 21.5, 23.7, 23.8, 23.10_
  - [x] 14.3 Show monthly solar radiation in the farm-data Climate view (already fetched and cached)
  - [x] 14.4 Create `Findings.jsx` and `TermInfo.jsx` (plain-language explanations of terms, keyboard-operable)
    - _Requirements: 4.4, 4.7_
  - [x] 14.5 Create `PriorityPicker.jsx`
    - Toggle buttons with `aria-pressed`, and the constraint radios.
    - A current-crop picker when the current rotation is unknown.
    - _Requirements: 6.5, 9.1, 9.2, 15.4_
  - [x] 14.6 Create `CalendarStrip.jsx`, `ScoreBars.jsx`, `StrategyCard.jsx` and `RuledOut.jsx`
    - Patterns and symbols as well as colour; per-month `aria-label`s.
    - Today and outlook scores, with "How was this scored?".
    - Expandable why, benefits, risks (amber local-review style), future risks, soil notes, gaps and confidence.
    - Crop source links.
    - _Requirements: 7.5, 8.1–8.7, 10.4, 11.1–11.6, 12.4_
  - [x] 14.7 Create `FieldSummary.jsx` and a short "Data and limitations" section
    - The section order from the design and the disclaimers.
    - The current card pinned first and "Best fit for your priorities" on the top alternative.
    - A live region announcing the new top strategy, and a one-column layout below 768 px.
    - "Data and limitations": every source with its resolution and licence, the crop table written for Central Texas, single-pixel crop map, map-unit soil averages.
    - _Requirements: 9.4, 9.7, 10.6, 12.1–12.5, 15.1–15.6_
  - [x] 14.8 Run `npm.cmd run build` in `frontend/` and fix any errors
    - _Requirements: 16.1_

- [ ] 15. Browser checks with Playwright
  - [ ] 15.1 Start the backend and the Vite dev server, then use the Playwright MCP to check against Webberwood:
    - scrolling from the map to the summary;
    - Ctrl + scroll zooms the map, while plain scrolling scrolls the page;
    - the soil block rotates with the arrow keys;
    - toggling priorities re-ranks the cards and the live region updates;
    - 375 px width shows one column with no sideways scroll;
    - reduced motion (media emulation) turns off the idle rotation;
    - light and dark themes;
    - no console errors.

    Save a screenshot for each check and fix what fails.
    - _Requirements: 1, 3, 9, 15_

- [x] 16. Final checks
  - [x] 16.1 Run the full backend test suite and `verify.py`; report each source's live status, including failures
  - [x] 16.2 Confirm `backend/cache/` is ignored, no `.env` values appear in code, logs, cache files, fixtures or the built frontend, and Open-Meteo is credited
    - _Requirements: 16.3, 18.11, 23.4_
    - 2026-11-15: `.env`, `backend/cache/`, `dist/` and the dev reports are in `.gitignore`; no key, token or variable name found in backend code, tests, scripts, cache, config, frontend source, `dist/` or fixtures; Open-Meteo CC BY 4.0 credit in `DataLimitations.jsx` and `ClimateTrends.jsx`.
    - 16.1 result (`verify.py`, 2026-11-15): 356 passed, 1 skipped, 1 deprecation warning; build OK; geocoders OK (Census, Nominatim, coordinates); farm-data live: NASA POWER 64, SSURGO 8, CDL 8 records; rotation: no missing sources, 4 strategies all high confidence, 6 findings, 5 exclusions, outlook precomputed; NWS weather: 14 periods, 0 official alerts, 1 farm alert.
  - [x] 16.3 Give the user the remaining manual checklist (screen reader, a real phone, a second location with an on-demand outlook)

## Phase 2 (after the deadline)

- [ ] 17. NASA NEX-GDDP-CMIP6 projection for demo farms
  - [ ] 17.1 Test whether the NCCS THREDDS subset service returns one point as CSV or NetCDF; choose the approach (a NetCDF reader would be a new package and needs approval)
  - [ ] 17.2 Write the precompute script, add the `outlook_source` switch, and add the demo-farm-only explanation
    - _Requirements: 19.1–19.5_
- [ ] 18. Advanced soil test form
  - [ ] 18.1 Add the `soil_*` parameters with range validation; Soil_Test values replace the SSURGO facts; "your soil test" tags; values never logged or stored on the backend
  - [ ] 18.2 Add the form, the "clear my soil test" control and browser-only storage
    - _Requirements: 20.1–20.7_
- [ ] 19. USDA Quick Stats market data
  - [ ] 19.1 Read `NASS_QUICKSTATS_API_KEY` from the environment; fetch county acreage and state prices; feed them into the income score with a fallback; show "no market data" when missing
    - _Requirements: 22.1–22.5_
- [ ] 20. Terrain slope and erosion risk from the terrain tiles, combined with the SSURGO K factor (shown spatially, per the honest 3D rule)
- [ ] 21. NLCD land cover as a point lookup, to explain single-pixel crop map results such as a wooded pixel
