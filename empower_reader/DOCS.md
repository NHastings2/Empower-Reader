# Empower Reader

This add-on logs into Naperville Empower, reads interval usage data, and publishes Home Assistant MQTT discovery sensors.

## Features

- Fetches the latest Empower dashboard usage data with Playwright
- Publishes MQTT discovery sensors for Home Assistant
- Maintains a running energy total in add-on persistent storage
- Polls automatically on a configurable interval

## Configuration

```yaml
empower_username: "your_empower_username"
empower_password: "your_empower_password"
mqtt_host: "core-mosquitto"
mqtt_port: 1883
mqtt_user: ""
mqtt_password: ""
poll_interval_minutes: 30
headless: true
try_headless_first: true
login_url: "https://www.empowernaperville.com"
dashboard_url: "https://www.empowernaperville.com/Dashboard"
device_id: "empower_naperville"
device_name: "Naperville Empower"
discovery_prefix: "homeassistant"
```

## Notes

- `mqtt_host` should point at your MQTT broker. If you use the Mosquitto add-on, `core-mosquitto` is a common value inside Home Assistant.
- If Empower challenges headless login, set `headless: false`.
- Persistent data is stored in the add-on `/data` volume.

## Install

1. Publish this repository to GitHub.
2. In Home Assistant, open Settings > Add-ons > Add-on Store.
3. Use the menu in the top right and add this GitHub repository URL as a third-party repository.
4. Install the `Empower Reader` add-on.
5. Fill in the add-on configuration and start it.
