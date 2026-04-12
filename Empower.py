#!/usr/bin/env python3
from __future__ import annotations

import sys

from empower_lib import fetch_empower_blob, load_settings


def main() -> int:
    settings = load_settings()
    data = fetch_empower_blob(settings)
    print(f"Wrote {settings.blob_json_path}")
    print(f"Top-level keys: {', '.join(list(data.keys())[:20])}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
