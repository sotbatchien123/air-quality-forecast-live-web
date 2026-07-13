const DATA_URL = "data/dashboard.json";
const REGIONS_URL = "data/model_regions.geojson";
const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

const provinceNames = {
  ba_ria_vung_tau: "Bà Rịa - Vũng Tàu",
  dong_nai: "Đồng Nai",
  ho_chi_minh: "TP. Hồ Chí Minh",
  long_an: "Long An",
  tay_ninh: "Tây Ninh",
};

let dashboard = null;
let regionGeoJson = null;
let selectedTargetAt = null;
let selectedMapLocationKey = null;
let userSelectedHistoricalTarget = false;
let dashboardLoading = false;

const $ = (id) => document.getElementById(id);

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return Number(value).toLocaleString("vi-VN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return `${formatNumber(Number(value) * 100, 1)}%`;
}

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("vi-VN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function categoryClass(category) {
  if (!category) return "Unknown";
  if (category === "Unhealthy for sensitive groups") return "Sensitive";
  if (category === "Very unhealthy") return "Very";
  return category.split(" ")[0];
}

function observationSourceLabel(row) {
  const sourceText = [
    row.traffic_source,
    row.aqi_source,
    row.weather_source,
  ].join(" ");
  return sourceText.includes("gap_fill") ? "Gap fill" : "Live";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isFiniteNumber(value) {
  return Number.isFinite(Number(value));
}

function visitCoordinates(coordinates, callback) {
  if (!Array.isArray(coordinates)) return;
  if (typeof coordinates[0] === "number" && typeof coordinates[1] === "number") {
    callback(coordinates);
    return;
  }
  coordinates.forEach((item) => visitCoordinates(item, callback));
}

function geoJsonBounds(features) {
  const lats = [];
  const lons = [];
  features.forEach((feature) => {
    visitCoordinates(feature.geometry?.coordinates, (point) => {
      if (isFiniteNumber(point[0]) && isFiniteNumber(point[1])) {
        lons.push(Number(point[0]));
        lats.push(Number(point[1]));
      }
    });
  });
  if (!lats.length || !lons.length) return null;
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const latPadding = Math.max((maxLat - minLat) * 0.12, 0.02);
  const lonPadding = Math.max((maxLon - minLon) * 0.12, 0.02);
  return {
    minLat: minLat - latPadding,
    maxLat: maxLat + latPadding,
    minLon: minLon - lonPadding,
    maxLon: maxLon + lonPadding,
  };
}

function projectLngLat(lon, lat, bounds) {
  const lonRange = bounds.maxLon - bounds.minLon || 1;
  const latRange = bounds.maxLat - bounds.minLat || 1;
  return {
    x: ((Number(lon) - bounds.minLon) / lonRange) * 100,
    y: ((bounds.maxLat - Number(lat)) / latRange) * 100,
  };
}

function ringPath(ring, bounds) {
  return `${ring
    .map((point, index) => {
      const projected = projectLngLat(point[0], point[1], bounds);
      return `${index === 0 ? "M" : "L"} ${projected.x.toFixed(2)} ${projected.y.toFixed(2)}`;
    })
    .join(" ")} Z`;
}

function geometryPath(geometry, bounds) {
  if (!geometry) return "";
  if (geometry.type === "Polygon") {
    return geometry.coordinates.map((ring) => ringPath(ring, bounds)).join(" ");
  }
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates
      .map((polygon) => polygon.map((ring) => ringPath(ring, bounds)).join(" "))
      .join(" ");
  }
  return "";
}

function targetKey(value) {
  return value ? String(value) : "";
}

function getHourlyForecasts(data = dashboard) {
  return data?.hourly_forecasts || [];
}

function ensureSelectedTarget(data) {
  const forecasts = getHourlyForecasts(data);
  if (!forecasts.length) {
    selectedTargetAt = data.latest_target_at || null;
    userSelectedHistoricalTarget = false;
    return;
  }
  const keys = forecasts.map((row) => targetKey(row.target_at));
  if (
    !userSelectedHistoricalTarget ||
    !selectedTargetAt ||
    !keys.includes(targetKey(selectedTargetAt))
  ) {
    selectedTargetAt = forecasts[0].target_at;
    userSelectedHistoricalTarget = false;
  }
}

function selectedForecast(data = dashboard) {
  return getHourlyForecasts(data).find(
    (row) => targetKey(row.target_at) === targetKey(selectedTargetAt),
  );
}

function predictionsForSelectedHour() {
  const allRows = dashboard.hourly_predictions || dashboard.predictions || [];
  if (!selectedTargetAt) return dashboard.predictions || [];
  return allRows.filter(
    (row) => targetKey(row.target_at) === targetKey(selectedTargetAt),
  );
}

function setStatus(data) {
  const dot = $("statusDot");
  const statusText = $("statusText");
  dot.className = "status-dot";
  if (data.status === "ready") {
    dot.classList.add("ready");
    statusText.textContent =
      "Model hourly đang cập nhật prediction từng giờ qua GitHub Actions";
  } else if (data.status === "warming_up_live_history") {
    statusText.textContent =
      "Model hourly đang gom lại 12 giờ live history trước khi sinh prediction mới";
  } else if (data.status === "live_collection_failed") {
    dot.classList.add("error");
    statusText.textContent =
      "Lần lấy dữ liệu live mới nhất lỗi; web đang giữ prediction gần nhất trong TiDB";
  } else if (data.status === "waiting_for_github_actions") {
    statusText.textContent = "Đang chờ GitHub Actions sinh dữ liệu lần đầu";
  } else {
    statusText.textContent = "Chưa có prediction mới, đang chờ đủ live history";
  }
}

function renderKpis(data) {
  const forecast = selectedForecast(data);
  const summary = forecast || data.summary || {};
  const targetAt = forecast?.target_at || selectedTargetAt || data.latest_target_at;
  $("latestTarget").textContent = formatDateTime(targetAt);
  $("generatedAt").textContent = `Generated: ${formatDateTime(data.generated_at)}`;
  $("latestObserved").textContent = `Observed: ${formatDateTime(data.latest_observed_at)}`;
  $("avgAqi").textContent = formatNumber(summary.avg_predicted_us_aqi, 1);
  $("maxAqi").textContent = formatNumber(summary.max_predicted_us_aqi, 1);
  $("avgSpeed").textContent = formatNumber(summary.avg_predicted_currentspeed, 1);
  $("predictionCount").textContent = formatNumber(summary.prediction_count, 0);
  $("maxAqiNote").textContent = "US AQI";
  $("selectedTargetLabel").textContent = `Đang xem: ${formatDateTime(targetAt)}`;
}

function renderHourlyForecasts(data) {
  const container = $("hourlyForecastGrid");
  const forecasts = getHourlyForecasts(data);
  if (!forecasts.length) {
    container.innerHTML = `<p class="muted">Chưa có lịch sử prediction hourly trong TiDB.</p>`;
    return;
  }
  container.innerHTML = forecasts
    .map((row) => {
      const active = targetKey(row.target_at) === targetKey(selectedTargetAt);
      return `
        <button class="hour-card ${active ? "active" : ""}" data-target="${row.target_at}">
          <span class="label">${formatDateTime(row.target_at)}</span>
          <strong>${formatNumber(row.avg_predicted_us_aqi, 1)} AQI</strong>
          <small>${formatNumber(row.prediction_count, 0)} địa điểm · max ${formatNumber(
            row.max_predicted_us_aqi,
            1,
          )}</small>
        </button>
      `;
    })
    .join("");

  container.querySelectorAll("[data-target]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTargetAt = button.getAttribute("data-target");
      userSelectedHistoricalTarget =
        targetKey(selectedTargetAt) !== targetKey(forecasts[0]?.target_at);
      render(dashboard);
    });
  });
}

function renderProvinceOptions(predictions) {
  const select = $("provinceFilter");
  const selected = select.value || "all";
  const keys = [...new Set(predictions.map((row) => row.province_key))].sort();
  select.innerHTML = `<option value="all">Tất cả tỉnh/thành</option>`;
  keys.forEach((key) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = provinceNames[key] || key;
    select.appendChild(option);
  });
  select.value = keys.includes(selected) ? selected : "all";
}

function renderProvinces(data) {
  const grid = $("provinceGrid");
  const provinces = selectedForecast(data)?.provinces || data.provinces || [];
  if (!provinces.length) {
    grid.innerHTML = `<p class="muted">Chưa có dữ liệu prediction theo tỉnh/thành.</p>`;
    return;
  }
  grid.innerHTML = provinces
    .map(
      (row) => `
        <article class="province-card">
          <span class="label">${provinceNames[row.province_key] || row.province_key}</span>
          <strong>${formatNumber(row.avg_predicted_us_aqi, 1)} AQI</strong>
          <dl>
            <dt>Số địa điểm</dt><dd>${formatNumber(row.location_count, 0)}</dd>
            <dt>AQI max</dt><dd>${formatNumber(row.max_predicted_us_aqi, 1)}</dd>
            <dt>Tốc độ TB</dt><dd>${formatNumber(row.avg_predicted_currentspeed, 1)}</dd>
            <dt>Mật độ TB</dt><dd>${formatPercent(row.avg_predicted_traffic_density)}</dd>
          </dl>
        </article>
      `,
    )
    .join("");
}

function renderCategoryBars(data) {
  const container = $("categoryBars");
  const counts =
    selectedForecast(data)?.aqi_category_counts || data.summary?.aqi_category_counts || {};
  const entries = Object.entries(counts);
  const total = entries.reduce((sum, [, value]) => sum + Number(value), 0);
  if (!entries.length || total === 0) {
    container.innerHTML = `<p class="muted">Chưa có dữ liệu nhóm AQI.</p>`;
    return;
  }
  container.innerHTML = entries
    .map(([category, count]) => {
      const percent = Math.round((Number(count) / total) * 100);
      const klass = categoryClass(category);
      return `
        <div class="bar-row">
          <span>${category}</span>
          <div class="bar-track">
            <div class="bar-fill ${klass}" style="width: ${percent}%"></div>
          </div>
          <strong>${count}</strong>
        </div>
      `;
    })
    .join("");
}

function renderMapDetail(row, feature) {
  const container = $("mapDetail");
  const properties = feature?.properties || {};
  if (!row && !feature) {
    container.innerHTML = `<p class="muted">Chưa có vùng nào trên bản đồ.</p>`;
    return;
  }
  if (!row) {
    container.innerHTML = `
      <p class="eyebrow">Selected Region</p>
      <h3>${escapeHtml(properties.display_name || properties.district_key)}</h3>
      <p class="muted">${escapeHtml(provinceNames[properties.province_key] || properties.province_key)}</p>
      <p class="muted">Vùng này có ranh giới GeoJSON nhưng chưa có prediction cho giờ đang chọn.</p>
      <dl>
        <dt>Nguồn ranh giới</dt><dd>${escapeHtml(properties.source || "GeoJSON")}</dd>
        <dt>GADM</dt><dd>${escapeHtml(properties.gadm_name_2 || "--")}</dd>
      </dl>
    `;
    return;
  }
  const category = row.aqi_category || "Unknown";
  container.innerHTML = `
    <p class="eyebrow">Selected Region</p>
    <h3>${escapeHtml(row.display_name || row.district_key)}</h3>
    <p class="muted">${escapeHtml(provinceNames[row.province_key] || row.province_key)}</p>
    <dl>
      <dt>Target</dt><dd>${formatDateTime(row.target_at)}</dd>
      <dt>AQI dự báo</dt><dd>${formatNumber(row.predicted_us_aqi, 1)}</dd>
      <dt>Nhóm AQI</dt><dd><span class="pill ${categoryClass(category)}">${escapeHtml(category)}</span></dd>
      <dt>Tốc độ</dt><dd>${formatNumber(row.predicted_currentspeed, 1)} km/h</dd>
      <dt>Mật độ</dt><dd>${formatPercent(row.predicted_traffic_density)}</dd>
      <dt>Ranh giới</dt><dd>${escapeHtml(properties.gadm_name_2 || row.display_name || "--")}</dd>
    </dl>
  `;
}

function renderPredictionMap() {
  const container = $("predictionMap");
  const features = regionGeoJson?.features || [];
  if (!features.length) {
    container.innerHTML = `<p class="muted">Không tải được GeoJSON ranh giới.</p>`;
    renderMapDetail(null, null);
    return;
  }

  const bounds = geoJsonBounds(features);
  if (!bounds) {
    container.innerHTML = `<p class="muted">GeoJSON không có tọa độ hợp lệ.</p>`;
    renderMapDetail(null, null);
    return;
  }
  const rows = predictionsForSelectedHour();
  const predictionByKey = new Map(rows.map((row) => [row.location_key, row]));
  const featureByKey = new Map(features.map((feature) => [feature.properties.location_key, feature]));
  const sortedRows = rows
    .slice()
    .sort((a, b) => Number(b.predicted_us_aqi || 0) - Number(a.predicted_us_aqi || 0));
  const firstMappedRow =
    sortedRows.find((row) => featureByKey.has(row.location_key)) || sortedRows[0];
  if (!selectedMapLocationKey || !featureByKey.has(selectedMapLocationKey)) {
    selectedMapLocationKey = firstMappedRow?.location_key || features[0].properties.location_key;
  }
  const activeRow =
    predictionByKey.get(selectedMapLocationKey) || firstMappedRow || null;
  const activeFeature =
    featureByKey.get(selectedMapLocationKey) ||
    (activeRow ? featureByKey.get(activeRow.location_key) : null) ||
    features[0];
  const regionMarkup = features
    .map((feature) => {
      const key = feature.properties.location_key;
      const row = predictionByKey.get(key);
      const category = row?.aqi_category || "Unknown";
      const selected = key === selectedMapLocationKey;
      const label = escapeHtml(feature.properties.display_name || feature.properties.district_key);
      const dataClass = row ? categoryClass(category) : "no-data";
      const path = geometryPath(feature.geometry, bounds);
      return `
        <path
            class="region-shape ${dataClass} ${selected ? "selected" : ""}"
            d="${path}"
            fill-rule="evenodd"
            data-location-key="${escapeHtml(key)}"
            tabindex="0"
            role="button"
            aria-label="${label}${row ? `, AQI ${formatNumber(row.predicted_us_aqi, 1)}` : ", chưa có prediction"}"
          >
            <title>${label}${row ? `: AQI ${formatNumber(row.predicted_us_aqi, 1)}` : ": chưa có prediction"}</title>
          </path>
      `;
    })
    .join("");

  container.innerHTML = `
    <svg viewBox="0 0 100 100" role="img" aria-label="GeoJSON map prediction ${formatDateTime(selectedTargetAt)}">
      <defs>
        <radialGradient id="mapGlow" cx="50%" cy="40%" r="65%">
          <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.22" />
          <stop offset="100%" stop-color="#0f172a" stop-opacity="0.08" />
        </radialGradient>
      </defs>
      <rect class="map-bg" x="0" y="0" width="100" height="100" rx="6" />
      <g class="map-grid">
        <path d="M 12 25 H 88 M 10 50 H 90 M 12 75 H 88" />
        <path d="M 25 10 V 90 M 50 7 V 93 M 75 10 V 90" />
      </g>
      <g class="region-layer">${regionMarkup}</g>
    </svg>
  `;

  container.querySelectorAll("[data-location-key]").forEach((point) => {
    const selectPoint = () => {
      selectedMapLocationKey = point.getAttribute("data-location-key");
      renderPredictionMap();
    };
    point.addEventListener("click", selectPoint);
    point.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectPoint();
      }
    });
  });
  renderMapDetail(activeRow, activeFeature);
}

function renderRunStatus(data) {
  const container = $("runStatus");
  const run = data.collector_runs?.[0];
  if (!run) {
    container.innerHTML = `<p class="muted">Chưa có collector run trong TiDB.</p>`;
    return;
  }
  container.innerHTML = `
    <dl>
      <dt>Status</dt><dd>${run.status}</dd>
      <dt>Scheduled</dt><dd>${formatDateTime(run.scheduled_at)}</dd>
      <dt>Finished</dt><dd>${formatDateTime(run.finished_at)}</dd>
      <dt>Observations</dt><dd>${formatNumber(run.observations_count, 0)}</dd>
      <dt>Predictions</dt><dd>${formatNumber(run.predictions_count, 0)}</dd>
    </dl>
    ${run.error_message ? `<p class="muted">${run.error_message}</p>` : ""}
  `;
}

function filteredPredictions() {
  const province = $("provinceFilter").value;
  const query = $("searchInput").value.trim().toLowerCase();
  return predictionsForSelectedHour()
    .filter((row) => province === "all" || row.province_key === province)
    .filter((row) => {
      const text = `${row.display_name || ""} ${row.district_key || ""}`.toLowerCase();
      return !query || text.includes(query);
    })
    .sort((a, b) => Number(b.predicted_us_aqi || 0) - Number(a.predicted_us_aqi || 0));
}

function renderPredictionTable() {
  const body = $("predictionRows");
  const rows = filteredPredictions();
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="muted">Không có dòng phù hợp.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((row) => {
      const category = row.aqi_category || "Unknown";
      return `
        <tr>
          <td><strong>${row.display_name || row.district_key}</strong></td>
          <td>${provinceNames[row.province_key] || row.province_key}</td>
          <td>${formatNumber(row.predicted_us_aqi, 1)}</td>
          <td><span class="pill ${categoryClass(category)}">${category}</span></td>
          <td>${formatNumber(row.predicted_currentspeed, 1)} km/h</td>
          <td>${formatPercent(row.predicted_traffic_density)}</td>
        </tr>
      `;
    })
    .join("");
}

function renderObservationTable(data) {
  const body = $("observationRows");
  const rows = (data.observations || [])
    .slice()
    .sort((a, b) => Number(b.us_aqi || 0) - Number(a.us_aqi || 0))
    .slice(0, 20);
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7" class="muted">Chưa có observation.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td><strong>${row.display_name || row.district_key}</strong></td>
          <td>${formatNumber(row.us_aqi, 1)}</td>
          <td>${formatNumber(row.pm2_5, 1)}</td>
          <td>${formatNumber(row.currentspeed, 1)} km/h</td>
          <td>${formatNumber(row.temperature_2m, 1)} °C</td>
          <td>${formatNumber(row.relative_humidity_2m, 1)}%</td>
          <td>${observationSourceLabel(row)}</td>
        </tr>
      `,
    )
    .join("");
}

function renderModelInfo(data) {
  const container = $("modelInfo");
  const model = data.models?.[0];
  if (!model) {
    container.innerHTML = `<p class="muted">Chưa có model registry.</p>`;
    return;
  }
  const rows = [
    ["Version", data.latest_model_version || model.model_version],
    ["Variant", model.variant],
    ["Algorithm", model.algorithm],
    ["Horizon", `${model.horizon_hours} hour(s)`],
    ["Feature count", model.feature_count],
    ["Registered", formatDateTime(model.registered_at)],
  ];
  container.innerHTML = rows
    .map(
      ([label, value]) => `
        <div class="model-row">
          <span class="label">${label}</span>
          <strong>${value || "--"}</strong>
        </div>
      `,
    )
    .join("");
}

function render(data) {
  dashboard = data;
  ensureSelectedTarget(data);
  setStatus(data);
  renderHourlyForecasts(data);
  renderKpis(data);
  renderProvinceOptions(predictionsForSelectedHour());
  renderProvinces(data);
  renderCategoryBars(data);
  renderPredictionMap();
  renderRunStatus(data);
  renderPredictionTable();
  renderObservationTable(data);
  renderModelInfo(data);
}

async function loadDashboard() {
  if (dashboardLoading) return;
  dashboardLoading = true;
  try {
    const timestamp = Date.now();
    const [dashboardResponse, regionsResponse] = await Promise.all([
      fetch(`${DATA_URL}?t=${timestamp}`, { cache: "no-store" }),
      fetch(`${REGIONS_URL}?t=${timestamp}`, { cache: "no-store" }),
    ]);
    if (!dashboardResponse.ok) throw new Error(`dashboard.json HTTP ${dashboardResponse.status}`);
    if (!regionsResponse.ok) throw new Error(`model_regions.geojson HTTP ${regionsResponse.status}`);
    regionGeoJson = await regionsResponse.json();
    render(await dashboardResponse.json());
  } catch (error) {
    $("statusDot").className = "status-dot error";
    $("statusText").textContent = `Không tải được dữ liệu web: ${error.message}`;
  } finally {
    dashboardLoading = false;
  }
}

$("provinceFilter").addEventListener("change", renderPredictionTable);
$("searchInput").addEventListener("input", renderPredictionTable);

loadDashboard();
setInterval(loadDashboard, REFRESH_INTERVAL_MS);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) loadDashboard();
});
