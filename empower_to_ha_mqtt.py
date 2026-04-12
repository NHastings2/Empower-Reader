#!/usr/bin/env python3
from __future__ import annotations

import sys

from empower_lib import load_json, load_settings, publish_to_home_assistant


def main() -> int:
    settings = load_settings()
    payload = load_json(settings.blob_json_path)
    result = publish_to_home_assistant(settings, payload)
    print(
        "Published total={total_kwh} kWh, last_interval={last_interval_kwh} kWh @ "
        "{last_interval_time}".format(**result)
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
