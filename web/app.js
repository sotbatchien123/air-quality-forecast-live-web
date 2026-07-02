const DATA_URL = "data/dashboard.json";

const provinceNames = {
  ba_ria_vung_tau: "Bà Rịa - Vũng Tàu",
  dong_nai: "Đồng Nai",
  ho_chi_minh: "TP. Hồ Chí Minh",
  long_an: "Long An",
  tay_ninh: "Tây Ninh",
};

let dashboard = null;
let selectedTargetAt = null;

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
    return;
  }
  const keys = forecasts.map((row) => targetKey(row.target_at));
  if (!selectedTargetAt || !keys.includes(targetKey(selectedTargetAt))) {
    selectedTargetAt = forecasts[0].target_at;
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
    body.innerHTML = `<tr><td colspan="6" class="muted">Chưa có observation.</td></tr>`;
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
  renderRunStatus(data);
  renderPredictionTable();
  renderObservationTable(data);
  renderModelInfo(data);
}

async function loadDashboard() {
  try {
    const response = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $("statusDot").className = "status-dot error";
    $("statusText").textContent = `Không tải được dashboard.json: ${error.message}`;
  }
}

$("provinceFilter").addEventListener("change", renderPredictionTable);
$("searchInput").addEventListener("input", renderPredictionTable);

loadDashboard();
