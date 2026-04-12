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

## Why this split exists

Empower serves an anti-bot challenge on direct non-browser login requests. The helper add-on handles that with Playwright, while the integration stays lightweight and creates native Home Assistant entities directly.
