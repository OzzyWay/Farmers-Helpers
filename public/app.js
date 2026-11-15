// Farmers Helpers front end: sends the address to /api/analyze and draws the report.

const $ = (sel) => document.querySelector(sel);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const thisMonth = new Date().getMonth();

let map, layerControl, markers, texasMap, texasRegionsLayer, regionMarkers, selectedTexasRegion, climateChart, report, cropFilter = "now";

const TEXAS_REGIONS = [
  { id: "panhandle", name: "Panhandle", coords: [[36.5, -103.05], [36.5, -100], [34.55, -100], [34.55, -101.5], [35, -102.8]], status: "Dry watch", tone: "dry", temp: 82, rain: "0.7 in", moisture: 24, outlook: "Dry topsoil and steady winds raise irrigation demand. Check stored water before expanding acreage.", crops: ["Winter wheat", "Grain sorghum", "Corn"], lookup: "Armstrong County, TX", resources: [{ kind: "E", type: "extension", name: "County extension office", detail: "Crop and soil guidance", lat: 35.2, lon: -101.8 }, { kind: "W", type: "water", name: "Irrigation support", detail: "Water planning", lat: 35.4, lon: -101.3 }] },
  { id: "trans-pecos", name: "Trans-Pecos", coords: [[32, -106.65], [32, -103.1], [30.5, -103.1], [29.5, -103.5], [28.7, -104.5], [29, -106.3], [31.8, -106.65]], status: "Very dry", tone: "dry", temp: 91, rain: "0.4 in", moisture: 18, outlook: "Very limited soil moisture. Prioritize livestock water checks and protect young plants from heat stress.", crops: ["Cotton", "Chiles", "Sorghum"], lookup: "Presidio County, TX", resources: [{ kind: "E", type: "extension", name: "Regional extension office", detail: "Range and crop advice", lat: 30.6, lon: -104.1 }, { kind: "S", type: "supply", name: "Farm and feed supply", detail: "Feed and equipment", lat: 30.9, lon: -103.7 }] },
  { id: "high-plains", name: "High Plains", coords: [[34.55, -103.1], [34.55, -101.5], [33.5, -100], [32.5, -100], [32.4, -103.1]], status: "Dry watch", tone: "dry", temp: 86, rain: "1.1 in", moisture: 31, outlook: "Warm and on the dry side. Irrigation scheduling and wind protection are the main near-term priorities.", crops: ["Cotton", "Grain sorghum", "Winter wheat"], lookup: "Lubbock County, TX", resources: [{ kind: "E", type: "extension", name: "AgriLife Extension", detail: "Lubbock County crop guidance", lat: 33.58, lon: -101.85 }, { kind: "W", type: "water", name: "Irrigation support", detail: "Water-use planning", lat: 33.9, lon: -101.4 }, { kind: "S", type: "supply", name: "Farm supply", detail: "Seed and equipment", lat: 33.2, lon: -101.7 }] },
  { id: "rolling-plains", name: "Rolling Plains", coords: [[34.55, -100], [34.55, -99], [33, -99], [31.5, -100.2], [32.4, -100.8], [33.5, -100]], status: "Watch", tone: "watch", temp: 84, rain: "1.8 in", moisture: 39, outlook: "Some stored moisture remains, but rainfall is uneven. Watch pasture recovery and early-season weeds.", crops: ["Wheat", "Cotton", "Forage sorghum"], lookup: "Haskell County, TX", resources: [{ kind: "E", type: "extension", name: "County extension office", detail: "Crop and range guidance", lat: 33.2, lon: -99.7 }, { kind: "S", type: "supply", name: "Feed and farm supply", detail: "Livestock and field supplies", lat: 32.8, lon: -99.4 }] },
  { id: "north-texas", name: "North Texas", coords: [[36.5, -100], [36.5, -94.5], [33.5, -94.5], [33.5, -96], [33, -97], [33, -99], [34.55, -99]], status: "Fair", tone: "fair", temp: 80, rain: "2.6 in", moisture: 48, outlook: "Moderate moisture supports pasture and small grains. Watch for runoff after heavy showers on compacted ground.", crops: ["Wheat", "Hay", "Oats"], lookup: "Wichita County, TX", resources: [{ kind: "E", type: "extension", name: "AgriLife Extension", detail: "North Texas field guidance", lat: 33.9, lon: -98.5 }, { kind: "W", type: "water", name: "Water district office", detail: "Local water planning", lat: 34.2, lon: -97.9 }] },
  { id: "east-texas", name: "East Texas", coords: [[33.5, -94.5], [33.5, -96], [32, -96], [31, -94.5], [31, -93.5], [33.5, -93.5]], status: "Steady", tone: "fair", temp: 79, rain: "3.4 in", moisture: 62, outlook: "Moisture is generally favorable. Maintain drainage on low ground and scout humid fields for disease pressure.", crops: ["Hay", "Corn", "Vegetables"], lookup: "Smith County, TX", resources: [{ kind: "E", type: "extension", name: "County extension office", detail: "Crop and livestock guidance", lat: 32.35, lon: -95.3 }, { kind: "S", type: "supply", name: "Farm supply", detail: "Seed and field inputs", lat: 32.6, lon: -94.9 }] },
  { id: "central-texas", name: "Central Texas", coords: [[32.4, -100.8], [31.5, -100.2], [29.5, -99], [29, -97], [31, -96], [32, -96], [33, -97], [33, -99]], status: "Watch", tone: "watch", temp: 85, rain: "2.0 in", moisture: 42, outlook: "Conditions vary between valleys and uplands. Check soil moisture before planting and keep livestock shade available.", crops: ["Hay", "Corn", "Small grains"], lookup: "McLennan County, TX", resources: [{ kind: "E", type: "extension", name: "AgriLife Extension", detail: "Central Texas crop guidance", lat: 31.55, lon: -97.15 }, { kind: "W", type: "water", name: "Water planning office", detail: "Drought and water resources", lat: 30.9, lon: -98.1 }] },
  { id: "south-texas", name: "South Texas", coords: [[29.5, -103.5], [29.5, -99], [27, -98], [25.84, -98.5], [25.84, -97], [29.5, -97], [29.5, -96], [31, -96], [31, -94.5], [29, -97], [29, -99]], status: "Dry watch", tone: "dry", temp: 90, rain: "1.0 in", moisture: 27, outlook: "Heat and limited rainfall can stress pasture and crops. Plan irrigation around establishment and check livestock water daily.", crops: ["Cotton", "Grain sorghum", "Forage"], lookup: "Webb County, TX", resources: [{ kind: "E", type: "extension", name: "County extension office", detail: "South Texas field guidance", lat: 27.5, lon: -99.5 }, { kind: "S", type: "supply", name: "Feed and farm supply", detail: "Livestock and equipment", lat: 27.3, lon: -99.2 }] },
  { id: "gulf-coast", name: "Gulf Coast", coords: [[31, -97], [29.5, -96], [29.5, -93.5], [26, -93.5], [26, -97], [27, -98], [29.5, -99]], status: "Moist", tone: "fair", temp: 83, rain: "4.1 in", moisture: 68, outlook: "Moisture is comparatively high. Check drainage and field access after rain, and monitor warm-season disease pressure.", crops: ["Rice", "Hay", "Vegetables"], lookup: "Brazoria County, TX", resources: [{ kind: "E", type: "extension", name: "AgriLife Extension", detail: "Coastal crop guidance", lat: 29.2, lon: -95.4 }, { kind: "W", type: "water", name: "Water management office", detail: "Drainage and irrigation", lat: 29.1, lon: -95.1 }] },
];

function initTexasDesk() {
  const usBounds = L.latLngBounds([24.3, -125], [49.5, -66.5]);
  texasMap = L.map("texas-map", { center: [39.8, -98.5], zoom: 4, minZoom: 3, maxZoom: 13, maxBounds: usBounds, maxBoundsViscosity: 1, zoomControl: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(texasMap);
  texasRegionsLayer = L.featureGroup().addTo(texasMap);
  regionMarkers = L.layerGroup().addTo(texasMap);
  const gpsLayer = L.layerGroup().addTo(texasMap);
  const depthScene = $("#depth-scene");
  const depthLabel = $("#depth-label");
  const depthSteps = [...document.querySelectorAll(".depth-step")];
  const grassColors = ["#8fc63d", "#64a82f", "#b1dc55", "#4c8d2d", "#d0eb72"];
  const buildGrass = (host, className, count = 110) => {
    if (!host) return null;
    const grassField = document.createElement("div");
    grassField.className = className;
    grassField.setAttribute("aria-hidden", "true");
    const blades = [];
    for (let index = 0; index < count; index += 1) {
      const blade = document.createElement("i");
      const x = (index / Math.max(1, count - 1)) * 100 + ((index * 17) % 7) - 3.5;
      const height = 26 + ((index * 29) % 50);
      const lean = ((index * 23) % 17) - 8;
      blade.className = "grass-blade";
      blade.dataset.x = String(x);
      blade.dataset.lean = String(lean);
      blade.style.setProperty("--x", `${x}%`);
      blade.style.setProperty("--height", `${height}%`);
      blade.style.setProperty("--lean", `${lean}deg`);
      blade.style.setProperty("--grass-color", grassColors[index % grassColors.length]);
      grassField.appendChild(blade);
      blades.push(blade);
    }
    host.appendChild(grassField);
    host.addEventListener("pointerenter", () => host.classList.add("grass-hover"));
    host.addEventListener("pointerleave", () => {
      host.classList.remove("grass-hover");
      host.style.removeProperty("--hover-x");
      blades.forEach((blade) => { blade.style.transform = ""; });
    });
    host.addEventListener("pointermove", (event) => {
      const bounds = host.getBoundingClientRect();
      const x = ((event.clientX - bounds.left) / bounds.width) * 100;
      const hoverX = Math.max(0, Math.min(100, x));
      host.style.setProperty("--hover-x", `${hoverX.toFixed(1)}%`);
      blades.forEach((blade) => {
        const bladeX = Number(blade.dataset.x);
        const influence = Math.max(0, 1 - Math.abs(hoverX - bladeX) / 24);
        const bendAway = hoverX > bladeX ? -18 * influence : 18 * influence;
        blade.style.transform = `rotate(${Number(blade.dataset.lean) + bendAway}deg)`;
      });
    });
    return grassField;
  };
  buildGrass(depthScene?.querySelector(".depth-grass"), "grass-field");
  buildGrass($(".desk-top-grass"), "desk-top-grass-field", 120);
  buildGrass($(".landing-hero"), "hero-grass-field", 150);
  let targetProgress = 0;
  let displayedProgress = 0;
  let depthFrame = 0;
  const animateDepth = () => {
    displayedProgress += (targetProgress - displayedProgress) * 0.14;
    depthScene.style.setProperty("--depth-progress", displayedProgress.toFixed(4));
    depthScene.style.setProperty("--depth-title-top", `${(6 + displayedProgress * 78).toFixed(2)}%`);
    if (Math.abs(targetProgress - displayedProgress) > 0.001) {
      depthFrame = requestAnimationFrame(animateDepth);
    } else {
      displayedProgress = targetProgress;
      depthFrame = 0;
    }
  };
  const updateDepthScene = () => {
    const viewportCenter = window.innerHeight * 0.52;
    const firstBounds = depthSteps[0].getBoundingClientRect();
    const lastBounds = depthSteps[depthSteps.length - 1].getBoundingClientRect();
    const firstCenter = firstBounds.top + firstBounds.height / 2;
    const lastCenter = lastBounds.top + lastBounds.height / 2;
    const travel = Math.max(1, lastCenter - firstCenter);
    const progress = Math.max(0, Math.min(1, (viewportCenter - firstCenter) / travel));
    targetProgress = progress;
    if (!depthFrame) depthFrame = requestAnimationFrame(animateDepth);

    const step = depthSteps.reduce((closest, candidate) => {
      const bounds = candidate.getBoundingClientRect();
      const center = bounds.top + bounds.height / 2;
      return Math.abs(center - viewportCenter) < Math.abs(closest.center - viewportCenter)
        ? { element: candidate, center }
        : closest;
    }, { element: depthSteps[0], center: depthSteps[0].getBoundingClientRect().top + depthSteps[0].getBoundingClientRect().height / 2 }).element;
    depthScene.dataset.depth = step.dataset.depthStep;
    depthLabel.textContent = step.dataset.label;
    depthSteps.forEach((item) => item.classList.toggle("is-current", item === step));
  };
  window.addEventListener("scroll", updateDepthScene, { passive: true });
  window.addEventListener("resize", updateDepthScene);
  updateDepthScene();

  for (const region of TEXAS_REGIONS) {
    region.layer = L.polygon(region.coords, {
      color: "#fbfaf6", weight: 2, fillColor: region.tone === "dry" ? "#aa956d" : region.tone === "watch" ? "#7b7651" : "#4e7455", fillOpacity: 0.38,
    }).addTo(texasRegionsLayer);
    region.layer.bindTooltip(region.name, { sticky: true, direction: "top" });
    region.layer.on("click", () => selectTexasRegion(region));
  }

  $("#analyze-region").addEventListener("click", () => {
    if (!selectedTexasRegion) return;
    $("#address").value = selectedTexasRegion.lookup;
    analyze(selectedTexasRegion.lookup);
  });
  $("#locate-farm").addEventListener("click", () => {
    if (!navigator.geolocation) {
      setStatus("Location is not available in this browser. Enter a U.S. address instead.", true);
      return;
    }
    const button = $("#locate-farm");
    button.disabled = true;
    setStatus("Finding your location…");
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      button.disabled = false;
      const position = [coords.latitude, coords.longitude];
      const region = TEXAS_REGIONS.find((item) => pointInRegion(position, item.coords));
      if (!region) {
        setStatus("Your location is outside the sample regions on this map. Search for a U.S. address instead.", true);
        return;
      }
      gpsLayer.clearLayers();
      L.circleMarker(position, { radius: 8, color: "#fff", weight: 3, fillColor: "#22231f", fillOpacity: 1 })
        .bindPopup("Your device location").addTo(gpsLayer);
      selectTexasRegion(region);
      texasMap.setView(position, Math.max(texasMap.getZoom(), 8));
      setStatus(`Showing your location in ${region.name}.`);
    }, () => {
      button.disabled = false;
      setStatus("We couldn't access your location. Enter a U.S. address instead.", true);
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  });
  selectTexasRegion(TEXAS_REGIONS.find((region) => region.id === "high-plains"), false);

  document.querySelectorAll("[data-begin]").forEach((button) => button.addEventListener("click", openDesk));
  $("#header-begin").addEventListener("click", () => $("#desk").hidden ? openDesk() : openLanding());
  $("#brand-home").addEventListener("click", (event) => { event.preventDefault(); openLanding(); });
  $("#explore-soil").addEventListener("click", () => $("#soil-story").scrollIntoView({ behavior: "smooth" }));
  $("#assistant-toggle").addEventListener("click", toggleAssistant);
  $("#assistant-close").addEventListener("click", toggleAssistant);
  $("#assistant-form").addEventListener("submit", sendAssistantMessage);
}

function pointInRegion(point, polygon) {
  const [latitude, longitude] = point;
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const [currentLat, currentLon] = polygon[index];
    const [previousLat, previousLon] = polygon[previous];
    const crosses = (currentLat > latitude) !== (previousLat > latitude)
      && longitude < ((previousLon - currentLon) * (latitude - currentLat)) / (previousLat - currentLat) + currentLon;
    if (crosses) inside = !inside;
  }
  return inside;
}

function selectTexasRegion(region, zoom = true) {
  selectedTexasRegion = region;
  TEXAS_REGIONS.forEach((item) => item.layer.setStyle({
    color: item === region ? "#24251f" : "#fbfaf6",
    weight: item === region ? 3 : 1.5,
    fillOpacity: item === region ? 0.68 : 0.3,
  }));
  if (zoom) texasMap.fitBounds(region.layer.getBounds(), { padding: [28, 28], maxZoom: 7 });
  $("#region-kicker").textContent = "Regional demo snapshot";
  $("#region-name").textContent = region.name;
  $("#region-location").textContent = `${region.lookup} · illustrative conditions`;
  $("#region-condition").textContent = region.status;
  $("#region-condition").className = `condition-tag ${region.tone}`;
  $("#region-outlook").textContent = region.outlook;
  $("#region-crops").innerHTML = region.crops.map((crop) => `<span>${esc(crop)}</span>`).join("");

  const metrics = [
    { label: "Temperature", value: `${region.temp}°F`, foot: "sample" },
    { label: "Rain · 30 days", value: region.rain, foot: "sample" },
    { label: "Soil moisture", value: `${region.moisture}%`, foot: region.moisture < 30 ? "Low" : region.moisture > 60 ? "Good" : "Moderate", meter: region.moisture },
  ];
  $("#region-metrics").innerHTML = metrics.map((metric) => `
    <div class="region-metric">
      <span>${esc(metric.label)}</span><strong>${esc(metric.value)}</strong>
      <small>${esc(metric.foot)}</small>
      ${metric.meter != null ? `<i class="moisture-meter"><b style="width:${metric.meter}%"></b></i>` : ""}
    </div>`).join("");

  $("#region-resources").innerHTML = region.resources.map((resource) => `
    <div class="resource-item">
      <span class="resource-marker ${resource.type}">${resource.kind}</span>
      <div><strong>${esc(resource.name)}</strong><span>${esc(resource.detail)}</span></div>
    </div>`).join("");

  regionMarkers.clearLayers();
  region.resources.forEach((resource) => {
    const icon = L.divIcon({ className: `map-resource ${resource.type}`, html: `<span>${esc(resource.kind)}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
    L.marker([resource.lat, resource.lon], { icon }).bindPopup(`<strong>${esc(resource.name)}</strong><br>${esc(resource.detail)}<br><small>Illustrative placement</small>`).addTo(regionMarkers);
  });

  if ($("#assistant").classList.contains("open")) addAssistantMessage(`Selected ${region.name}. Ask me about its sample moisture, crops, or field outlook.`, "bot");
}

function openDesk() {
  $("#landing").hidden = true;
  $("#desk").hidden = false;
  $("#header-begin").textContent = "Back to home";
  $("#assistant-toggle").hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
  window.setTimeout(() => $("#desk").focus(), 0);
  setTimeout(() => texasMap.invalidateSize(), 100);
}

function openLanding() {
  $("#desk").hidden = true;
  $("#landing").hidden = false;
  $("#header-begin").textContent = "Open field desk ↗";
  $("#assistant").hidden = true;
  $("#assistant").classList.remove("open");
  $("#assistant-toggle").hidden = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
  window.setTimeout(() => $("#landing").focus(), 0);
}

function toggleAssistant() {
  const panel = $("#assistant");
  const opening = panel.hidden || !panel.classList.contains("open");
  panel.hidden = !opening;
  panel.classList.toggle("open", opening);
  $("#assistant-toggle").setAttribute("aria-expanded", String(opening));
  if (opening) $("#assistant-input").focus();
}

function addAssistantMessage(text, sender) {
  const message = document.createElement("p");
  message.className = `assistant-bubble ${sender}`;
  message.textContent = text;
  $("#assistant-messages").append(message);
  $("#assistant-messages").scrollTop = $("#assistant-messages").scrollHeight;
}

function sendAssistantMessage(event) {
  event.preventDefault();
  const input = $("#assistant-input");
  const question = input.value.trim();
  if (!question || !selectedTexasRegion) return;
  addAssistantMessage(question, "user");
  const query = question.toLowerCase();
  let answer = selectedTexasRegion.outlook;
  if (/soil|moisture|water|rain|dry/.test(query)) answer = `${selectedTexasRegion.name} has an illustrative soil-moisture reading of ${selectedTexasRegion.moisture}% and ${selectedTexasRegion.rain} of sample rainfall over 30 days. These are demo values, not live readings.`;
  else if (/crop|plant|grow|seed/.test(query)) answer = `The sample crop focus for ${selectedTexasRegion.name} is ${selectedTexasRegion.crops.join(", ")}. Use the address analysis for localized planting windows.`;
  else if (/temperature|temp|hot|heat/.test(query)) answer = `The ${selectedTexasRegion.name} demo snapshot shows ${selectedTexasRegion.temp}°F. Treat it as illustrative, not a current forecast.`;
  input.value = "";
  addAssistantMessage(answer, "bot");
}

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
const toF = (c) => Math.round(c * 9 / 5 + 32);
const toIn = (mm) => (mm / 25.4).toFixed(1);
const isoDaysAgo = (n) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10);

function setStatus(html, isError = false) {
  const el = $("#status");
  el.innerHTML = html;
  el.classList.toggle("error", isError);
}

// ---------- search ----------
async function analyze(address) {
  const btn = $("#go");
  btn.disabled = true;
  setStatus('<span class="spinner"></span>Finding your land on Google Maps, then pulling NASA climate and USDA soil data…');
  try {
    const res = await fetch(`/api/analyze?address=${encodeURIComponent(address)}`);
    const data = await res.json().catch(() => ({ error: "The server sent back something unexpected." }));
    if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);
    report = data;
    setStatus("");
    render(data);
  } catch (err) {
    setStatus(esc(err.message === "Failed to fetch" ? "Can't reach the server. Is server.py running?" : err.message), true);
  } finally {
    btn.disabled = false;
  }
}

$("#search").addEventListener("submit", (e) => {
  e.preventDefault();
  const address = $("#address").value.trim();
  if (address) analyze(address);
});
document.querySelectorAll(".ex").forEach((b) => b.addEventListener("click", () => {
  $("#address").value = b.textContent;
  analyze(b.textContent);
}));

// ---------- render ----------
function render(d) {
  $("#report").hidden = false;
  renderPlace(d.location);
  renderStats(d);
  renderForecast(d.weather);
  renderAlerts(d.weather?.alerts || []);
  renderMap(d);
  renderAdvice(d.advice);
  renderCrops();
  renderClimate(d.climate);
  renderSoil(d.soil);
  renderWeb(d.web);
  $("#warnings").textContent = d.warnings?.length ? `Some data was unavailable: ${d.warnings.join("; ")}` : "";
  $("#report").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderPlace(loc) {
  $("#place-county").textContent = [loc.county, loc.state].filter(Boolean).join(", ");
  $("#place-name").textContent = loc.label;
  $("#place-addr").textContent = loc.address;
  $("#place-coords").textContent = `${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`;
}

function renderStats(d) {
  const c = d.climate, r = d.recent, s = d.soil || {};
  const stats = [];
  stats.push({ label: `Average temp in ${MONTHS[thisMonth]}`, value: `${toF(c.temp_c[thisMonth])}°F`, sub: "NASA 20+ yr average" });
  if (r) {
    const normal = c.rain_mm[thisMonth];
    const pct = normal > 0 ? Math.round((r.rain_mm / normal) * 100) : null;
    stats.push({ label: `Rain, last ${r.days} days`, value: `${toIn(r.rain_mm)} in`, sub: pct == null ? "" : `${pct}% of a normal month` });
    if (r.topsoil_moisture != null) {
      stats.push({ label: "Topsoil moisture (NASA)", value: `${Math.round(r.topsoil_moisture * 100)}%`, sub: r.topsoil_moisture < 0.3 ? "Dry" : r.topsoil_moisture > 0.75 ? "Wet" : "OK", meter: r.topsoil_moisture });
    }
    if (r.low_c_7day != null) stats.push({ label: "Coldest night, last 7 days", value: `${toF(r.low_c_7day)}°F`, sub: r.low_c_7day <= 0 ? "Frost" : "No frost" });
  }
  stats.push({ label: "Yearly rain", value: `${toIn(c.annual_rain_mm)} in`, sub: c.annual_rain_mm < 500 ? "Dry climate, irrigation helps" : "NASA average" });
  if (s.ph != null) stats.push({ label: "Soil pH", value: s.ph, sub: s.texture || "" });
  $("#stats").innerHTML = stats.map((x) => `
    <div class="stat">
      <div class="label">${esc(x.label)}</div>
      <div class="value">${esc(x.value)}</div>
      <div class="sub">${esc(x.sub)}</div>
      ${x.meter != null ? `<div class="meter"><i style="width:${Math.round(x.meter * 100)}%"></i></div>` : ""}
    </div>`).join("");
}

// ---------- weather forecast + alerts ----------
const DISMISSED_KEY = "fh-dismissed-alerts";

function dismissedIds() {
  try { return new Set(JSON.parse(localStorage.getItem(DISMISSED_KEY) || "[]")); } catch { return new Set(); }
}
function saveDismissed(ids) {
  try { localStorage.setItem(DISMISSED_KEY, JSON.stringify([...ids].slice(-200))); } catch { /* private mode: just don't remember */ }
}

function renderForecast(w) {
  const card = $("#forecast-card");
  card.hidden = !w;
  if (!w) return;
  $("#forecast-link").href = safeUrl(w.page);
  // Pair each daytime period with the night after it (the first entry may be "Tonight" alone).
  const days = [];
  for (let i = 0; i < w.periods.length; i++) {
    const p = w.periods[i];
    if (p.is_day) {
      const night = w.periods[i + 1] && !w.periods[i + 1].is_day ? w.periods[i + 1] : null;
      days.push({ day: p, night });
      if (night) i++;
    } else {
      days.push({ day: null, night: p });
    }
  }
  const alertDays = new Set((w.alerts || []).map((a) => (a.until || "").slice(0, 10)));
  $("#forecast").innerHTML = days.slice(0, 7).map(({ day, night }) => {
    const main = day || night;
    const label = !day ? night.name : /^(This Afternoon|This Morning|Today)$/.test(day.name) ? "Today" : day.name;
    const rain = Math.max(day?.rain_pct || 0, night?.rain_pct || 0);
    const lo = night?.temp_f;
    const dates = [day?.start, night?.start].filter(Boolean).map((s) => s.slice(0, 10));
    return `<div class="day ${dates.some((d) => alertDays.has(d)) ? "alerting" : ""}" title="${esc(main.detail || main.short)}">
      <span class="name">${esc(label)}</span>
      ${main.icon ? `<img src="${esc(safeUrl(main.icon))}" alt="">` : ""}
      <span class="temps">${day ? `${day.temp_f}°` : ""}${lo != null ? ` <span class="lo ${lo <= 32 ? "freeze" : ""}">${day ? "/ " : ""}${lo}°</span>` : ""}</span>
      <span class="short">${esc(main.short)}</span>
      ${rain ? `<span class="rain">💧 ${rain}%</span>` : ""}
    </div>`;
  }).join("");
}

function renderAlerts(alerts, { showAll = false } = {}) {
  const box = $("#alerts");
  const dismissed = dismissedIds();
  const visible = showAll ? alerts : alerts.filter((a) => !dismissed.has(a.id));
  box.innerHTML = visible.map((a) => `
    <div class="alert ${esc(a.level)}" data-id="${esc(a.id)}" role="alert">
      <div class="kicker">${a.level === "danger" ? "⚠ Warning" : a.level === "warn" ? "⚠ Heads up" : "ℹ Note"} · ${esc(a.source)}</div>
      <b>${esc(a.title)}</b>
      <p>${esc(a.text)}</p>
      ${a.detail ? `<details><summary>Full NWS details</summary><pre>${esc(a.detail)}</pre></details>` : ""}
      <button class="close" type="button" aria-label="Close this alert" title="Close">×</button>
    </div>`).join("");
  box.querySelectorAll(".alert .close").forEach((btn) => btn.addEventListener("click", () => {
    const el = btn.closest(".alert");
    const ids = dismissedIds();
    ids.add(el.dataset.id);
    saveDismissed(ids);
    el.classList.add("leaving");
    // Remove after the slide-out; a timer (not animationend) so it also works with animations paused or off.
    setTimeout(() => { el.remove(); updateShowAlerts(alerts); }, 200);
  }));
  updateShowAlerts(alerts);
}

function updateShowAlerts(alerts) {
  const btn = $("#show-alerts");
  const open = $("#alerts").children.length;
  btn.hidden = !alerts.length || open === alerts.length;
  btn.textContent = `⚠ Show ${alerts.length} weather alert${alerts.length === 1 ? "" : "s"}`;
}

$("#show-alerts").addEventListener("click", () => {
  if (report?.weather) renderAlerts(report.weather.alerts, { showAll: true });
});

function nasaLayer(layer, date, ext, maxZoom) {
  return L.tileLayer(
    `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${layer}/default/${date}/GoogleMapsCompatible_Level${maxZoom}/{z}/{y}/{x}.${ext}`,
    { maxNativeZoom: maxZoom, maxZoom: 18, attribution: "NASA GIBS", opacity: 0.85 },
  );
}

function pin(color) {
  return L.divIcon({ className: "", html: `<i class="dot" style="background:${color};width:14px;height:14px"></i>`, iconSize: [14, 14], iconAnchor: [7, 7] });
}

function renderMap(d) {
  const { lat, lon, label } = d.location;
  if (!map) {
    map = L.map("map", { scrollWheelZoom: false });
    const streets = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
    layerControl = L.control.layers({
      "Street map": streets,
      "Satellite photo (NASA MODIS)": nasaLayer("MODIS_Terra_CorrectedReflectance_TrueColor", isoDaysAgo(2), "jpg", 9),
    }, {
      "Plant health / greenness (NASA NDVI)": nasaLayer("MODIS_Terra_NDVI_8Day", isoDaysAgo(14), "png", 9),
      "Root-zone soil moisture (NASA SMAP)": nasaLayer("SMAP_L4_Analyzed_Root_Zone_Soil_Moisture", isoDaysAgo(4), "png", 6),
    }, { collapsed: true }).addTo(map);
    markers = L.layerGroup().addTo(map);
  }
  markers.clearLayers();
  const bounds = [[lat, lon]];
  L.marker([lat, lon], { icon: pin("#c0392b") }).bindPopup(`<b>${esc(label)}</b><br>Your land`).addTo(markers);
  for (const p of d.web.local) {
    const color = p.kind === "Extension office" ? "#2f6b3a" : "#8a5a34";
    L.marker([p.lat, p.lon], { icon: pin(color) }).bindPopup(`
      <b>${esc(p.name)}</b><br>${esc(p.kind)}<br>${esc(p.address)}
      ${p.phone ? `<br>${esc(p.phone)}` : ""}${p.rating ? `<br>★ ${esc(p.rating)}` : ""}
      ${p.website ? `<br><a href="${esc(safeUrl(p.website))}" target="_blank" rel="noopener">Website</a>` : ""}`).addTo(markers);
    bounds.push([p.lat, p.lon]);
  }
  map.fitBounds(bounds, { padding: [30, 30], maxZoom: 11 });
  setTimeout(() => map.invalidateSize(), 50);
}

function renderAdvice(advice) {
  const group = (title, tips) => tips.length
    ? `<div class="tip-group">${title}</div>` + tips.map((t) => `<div class="tip ${esc(t.level)}"><b>${esc(t.title)}</b><p>${esc(t.text)}</p></div>`).join("")
    : "";
  $("#advice").innerHTML = group("Weather & water right now", advice.conditions) + group("Your soil", advice.soil)
    || '<p class="empty">No advice available.</p>';
}

function renderCrops() {
  const crops = report.crops;
  const el = $("#crops");
  if (cropFilter === "calendar") {
    el.innerHTML = `<div class="calendar"><table>
      <thead><tr><th></th>${MONTHS.map((m, i) => `<th class="${i === thisMonth ? "now" : ""}">${m}</th>`).join("")}</tr></thead>
      <tbody>${crops.map((c) => `<tr><td class="name">${esc(c.crop)}</td>${c.months.map((on, i) =>
        `<td class="m ${on ? "on" : ""} ${i === thisMonth ? "now" : ""}" title="${esc(c.crop)}: ${on ? "good" : "not a good"} month to plant (${MONTHS[i]})"></td>`).join("")}</tr>`).join("")}</tbody>
    </table><p class="fine" style="margin-top:8px">Green = good month to plant. Outlined column = this month.</p></div>`;
    return;
  }
  const list = crops.filter((c) => c.status === cropFilter);
  if (!list.length) {
    el.innerHTML = `<p class="empty">${cropFilter === "now" ? "Nothing on our list is a good fit to plant this month. Check \"Coming up\"." : "Nothing in this group."}</p>`;
    return;
  }
  el.innerHTML = `<div class="crop-grid">${list.map((c) => `
    <article class="crop">
      <div class="crop-top"><h4>${esc(c.crop)}</h4><span class="kind">${esc(c.kind)}</span></div>
      <div class="when">${esc(c.when)}</div>
      <div class="meta">
        <span class="chip">~${c.days} days to harvest</span>
        <span class="chip">${esc(c.water)} water</span>
        ${c.soil_ok ? "" : '<span class="chip bad">soil pH off</span>'}
      </div>
      <ul>${c.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    </article>`).join("")}</div>`;
}

document.querySelectorAll("#crop-tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#crop-tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  $("#crops").setAttribute("aria-labelledby", b.id);
  cropFilter = b.dataset.filter;
  if (report) renderCrops();
}));

function renderClimate(c) {
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue("--muted").trim(), line = css.getPropertyValue("--line").trim();
  climateChart?.destroy();
  climateChart = new Chart($("#climate-chart"), {
    data: {
      labels: MONTHS,
      datasets: [
        { type: "line", label: "Avg temp (°F)", data: c.temp_c.map(toF), yAxisID: "t", borderColor: "#d99a1e", backgroundColor: "#d99a1e", tension: 0.35, pointRadius: MONTHS.map((_, i) => (i === thisMonth ? 6 : 3)) },
        { type: "bar", label: "Rain (in)", data: c.rain_mm.map((mm) => +(mm / 25.4).toFixed(2)), yAxisID: "r", backgroundColor: MONTHS.map((_, i) => (i === thisMonth ? "#2b6c8f" : "rgba(43,108,143,0.45)")), borderRadius: 4 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: ink, boxWidth: 12 } } },
      scales: {
        x: { ticks: { color: ink }, grid: { display: false } },
        t: { position: "left", ticks: { color: ink, callback: (v) => `${v}°F` }, grid: { color: line } },
        r: { position: "right", ticks: { color: ink, callback: (v) => `${v}"` }, grid: { display: false }, beginAtZero: true },
      },
    },
  });
}

function renderSoil(s) {
  $("#soil-source").textContent = s?.source || "";
  if (!s || s.ph == null) {
    $("#soil").innerHTML = `<p class="soil-name">${esc(s?.name || "Unknown")}</p><p class="muted">${esc(s?.note || "No soil data for this spot.")}</p>`;
    return;
  }
  const fact = (label, value) => (value == null || value === "" ? "" : `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`);
  const bar = s.sand != null && s.clay != null
    ? `<div class="texture-bar" title="Sand / silt / clay">
         <div class="t-sand" style="width:${s.sand}%">${s.sand >= 12 ? `Sand ${Math.round(s.sand)}%` : ""}</div>
         <div class="t-silt" style="width:${s.silt ?? 0}%">${(s.silt ?? 0) >= 12 ? `Silt ${Math.round(s.silt)}%` : ""}</div>
         <div class="t-clay" style="width:${s.clay}%">${s.clay >= 12 ? `Clay ${Math.round(s.clay)}%` : ""}</div>
       </div>` : "";
  $("#soil").innerHTML = `
    <p class="soil-name">${esc(s.name)}</p>
    ${s.series ? `<p class="muted small" style="margin:0">Soil series: ${esc(s.series)}</p>` : ""}
    <div class="soil-facts">
      ${fact("Texture", s.texture)}
      ${fact("pH", s.ph)}
      ${fact("Organic matter", s.organic_matter != null ? `${s.organic_matter}%` : null)}
      ${fact("Drainage", s.drainage)}
      ${fact("Water it holds", s.water_capacity != null ? `${s.water_capacity} in per in of soil` : null)}
    </div>
    ${bar}
    ${s.note ? `<p class="fine" style="margin-top:10px">${esc(s.note)}</p>` : ""}`;
}

function renderWeb(w) {
  const item = (href, title, src) => `<li><a href="${esc(safeUrl(href))}" target="_blank" rel="noopener">${esc(title)}</a><span class="src">${esc(src)}</span></li>`;
  $("#guides").innerHTML = w.guides.map((g) => item(g.link, g.title, g.source)).join("") || '<li class="muted">No extension guides found.</li>';
  $("#local").innerHTML = w.local.map((p) => item(
    p.website || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${p.name} ${p.address}`)}`,
    p.name, [p.kind, p.address, p.phone].filter(Boolean).join(" · "),
  )).join("") || '<li class="muted">Nothing found nearby.</li>';
  $("#news").innerHTML = w.news.map((n) => item(n.link, n.title, [n.source, n.date].filter(Boolean).join(" · "))).join("") || '<li class="muted">No recent news found.</li>';
}

initTexasDesk();
