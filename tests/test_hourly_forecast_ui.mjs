import assert from "node:assert/strict";
import test from "node:test";

import {
  HOURLY_FORECAST_CARD_LIMIT,
  findHourlyForecastByLookup,
  hiddenHourlyForecastCount,
  visibleHourlyForecasts,
} from "../web/hourly-forecast-utils.mjs";

const forecasts = [
  "2026-07-14T00:00:00",
  "2026-07-13T23:00:00",
  "2026-07-13T22:00:00",
  "2026-07-13T21:00:00",
  "2026-07-13T20:00:00",
  "2026-07-13T19:00:00",
  "2026-07-13T18:00:00",
  "2026-07-13T17:00:00",
].map((target_at) => ({ target_at }));

test("hourly cards show only the newest six forecasts", () => {
  const visible = visibleHourlyForecasts(forecasts);

  assert.equal(visible.length, HOURLY_FORECAST_CARD_LIMIT);
  assert.equal(visible[0].target_at, "2026-07-14T00:00:00");
  assert.equal(visible.at(-1).target_at, "2026-07-13T19:00:00");
  assert.equal(forecasts.length, 8);
});

test("hourly history reports the count that remains searchable", () => {
  assert.equal(hiddenHourlyForecastCount(forecasts), 2);
  assert.equal(hiddenHourlyForecastCount(forecasts.slice(0, 6)), 0);
  assert.equal(hiddenHourlyForecastCount([]), 0);
});

test("hourly lookup opens an older forecast using date and hour", () => {
  const forecast = findHourlyForecastByLookup(forecasts, "2026-07-13 18:00");

  assert.equal(forecast?.target_at, "2026-07-13T18:00:00");
  assert.equal(findHourlyForecastByLookup(forecasts, "2026-07-13 16:00"), null);
  assert.equal(findHourlyForecastByLookup(forecasts, "not a timestamp"), null);
});
