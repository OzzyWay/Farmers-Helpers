// Farmers Helpers front end: sends the address to /api/analyze and draws the report.

const $ = (sel) => document.querySelector(sel);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const thisMonth = new Date().getMonth();

let map, layerControl, markers, climateChart, report, cropFilter = "now";

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
  stats.push({ label: `Average temp in ${MONTHS[thisMonth]}`, value: `${toF(c.temp_c[thisMonth])}°F`, sub: `${c.temp_c[thisMonth].toFixed(0)}°C · NASA 20+ yr average` });
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
        t: { position: "left", ticks: { color: ink, callback: (v) => `${v}°` }, grid: { color: line } },
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
