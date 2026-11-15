"""CLI runner for Member 3 Phase M3.4 DRSA, SA, and RCM evaluation."""

from __future__ import annotations

import sys

from bmp.experiments.member3_m3_4 import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
