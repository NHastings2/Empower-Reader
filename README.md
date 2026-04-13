# Empower Reader

This repository contains two Home Assistant pieces that work together:

- A HACS-installable custom integration that creates native entities
- A helper add-on that uses Playwright to log into Empower and write a JSON data file

## Recommended setup

1. Add this repo as a third-party add-on repository in Home Assistant and install `Empower Reader Helper`.
2. Configure the helper add-on with your Empower credentials and start it.
3. Add this same repo to HACS as a custom repository with category `Integration`.
4. Install `Empower Reader` through HACS and restart Home Assistant.
5. Add the integration from Settings > Devices & Services.
6. Use `empower_reader/latest.json` as the helper data file unless you changed the helper output path.

## Refresh and Energy

- Call the `empower_reader.refresh` service to force an immediate reload of the latest helper data.
- A native `button.empower_reader_refresh` entity is also created on the Empower device so you can trigger a manual refresh from the device page or dashboard.
- `sensor.empower_reader_electric_total` is the native long-term energy sensor intended for Home Assistant Energy dashboard use.
- New 15-minute intervals are aggregated into hourly energy statistics for Home Assistant, because the recorder only accepts imported statistics at the top of the hour. Partial hours are held until enough 15-minute intervals arrive to build a complete hourly total.
- `sensor.empower_reader_electric_estimated_demand` is a derived watts sensor based on the last 15-minute interval and is useful for dashboards, but it is not a true live real-time demand feed.
- `sensor.empower_reader_helper_last_fetch` and `sensor.empower_reader_helper_data_age` help you see when the helper data is stale.
- `sensor.empower_reader_first_available_interval` and `sensor.empower_reader_available_interval_count` show how much raw history was found in the helper payload.
- `sensor.empower_reader_last_imported_interval` shows the most recent 15-minute interval timestamp that was successfully imported into Home Assistant.
- `sensor.empower_reader_electric_last_interval_time` shows the most recent interval timestamp reported in the current Empower helper file.

## Why this split exists

Empower serves an anti-bot challenge on direct non-browser login requests. The helper add-on handles that with Playwright, while the integration stays lightweight and creates native Home Assistant entities directly.
