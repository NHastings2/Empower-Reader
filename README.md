# Empower Reader

Small Python utility for pulling interval data from Naperville Empower and publishing it to Home Assistant through MQTT discovery.

## What changed

- Secrets are now read from environment variables instead of being hardcoded in source.
- Paths are centralized so cache and data files always live under `data/` by default.
- A new `empower_sync.py` script fetches and publishes in one step.
- The original `Empower.py` and `empower_to_ha_mqtt.py` files remain as thin wrappers.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
playwright install chromium
```

3. Copy `.env.example` into your preferred environment loader, or set these variables manually:

```powershell
$env:EMPOWER_USERNAME="your_username"
$env:EMPOWER_PASSWORD="your_password"
$env:MQTT_HOST="192.168.1.10"
$env:MQTT_USER="mqtt_user"
$env:MQTT_PASS="mqtt_password"
```

## Usage

Fetch only:

```powershell
python .\Empower.py
```

Publish a previously saved blob:

```powershell
python .\empower_to_ha_mqtt.py
```

Fetch and publish in one step:

```powershell
python .\empower_sync.py
```

## Home Assistant

Enable MQTT discovery in Home Assistant and point the script at the same broker. After the first successful run, these sensors should appear automatically:

- `sensor.empower_electric_total`
- `sensor.empower_electric_last_interval`
- `sensor.empower_electric_last_interval_time`

The easiest Home Assistant flow is to run `empower_sync.py` on a schedule from the machine that can reach both Empower and your MQTT broker.

## Notes

- Empower sometimes pads the raw interval string with empty values. The parser now trims or fills reads to the exact expected interval count.
- The running total is cached under `data/empower_state_cache.json` so repeated publishes only add newly seen intervals.
- If headless login gets challenged, set `EMPOWER_HEADLESS=false` for a manual browser run.
