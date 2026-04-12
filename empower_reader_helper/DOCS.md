# Empower Reader Helper

This add-on uses Playwright to log into Naperville Empower and writes a JSON file that the `Empower Reader` HACS integration reads to create native Home Assistant entities.

## Install order

1. Install and start this add-on first.
2. Confirm it has written a data file.
3. Install the `Empower Reader` integration through HACS.
4. In the integration config flow, point it at the same data file path relative to `/config`.

## Configuration

```yaml
empower_username: "your_empower_username"
empower_password: "your_empower_password"
poll_interval_minutes: 30
output_path: "/config/empower_reader/latest.json"
login_url: "https://www.empowernaperville.com"
dashboard_url: "https://www.empowernaperville.com/Dashboard"
headless: true
try_headless_first: true
```

## Notes

- The add-on stores Playwright session state under `/data`.
- If headless mode is challenged, set `headless: false`.
- The integration should use `empower_reader/latest.json` as its helper data file when you keep the default output path.
