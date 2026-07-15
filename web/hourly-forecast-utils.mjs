export const HOURLY_FORECAST_CARD_LIMIT = 6;

export function visibleHourlyForecasts(
  forecasts,
  limit = HOURLY_FORECAST_CARD_LIMIT,
) {
  if (!Array.isArray(forecasts) || limit <= 0) return [];
  return forecasts.slice(0, limit);
}

export function hiddenHourlyForecastCount(
  forecasts,
  limit = HOURLY_FORECAST_CARD_LIMIT,
) {
  if (!Array.isArray(forecasts)) return 0;
  return Math.max(forecasts.length - Math.max(limit, 0), 0);
}

export function normalizeHourlyLookup(value) {
  const match = String(value ?? "")
    .trim()
    .match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?$/);
  return match ? `${match[1]}T${match[2]}` : "";
}

export function findHourlyForecastByLookup(forecasts, lookupValue) {
  const lookup = normalizeHourlyLookup(lookupValue);
  if (!lookup || !Array.isArray(forecasts)) return null;
  return (
    forecasts.find(
      (forecast) => normalizeHourlyLookup(forecast?.target_at) === lookup,
    ) || null
  );
}
