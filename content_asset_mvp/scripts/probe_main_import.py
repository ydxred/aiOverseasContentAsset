"""Probe whether app.main can be imported with the current environment."""
from __future__ import annotations

import importlib
import sys
import traceback


def main() -> int:
    try:
        importlib.import_module("app.main")
    except Exception:
        traceback.print_exc()
        return 1
    print("ok: app.main imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
