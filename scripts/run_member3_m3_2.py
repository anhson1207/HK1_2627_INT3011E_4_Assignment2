"""Entrypoint for the Phase M3.2 controlled SAT pilot benchmark."""

from __future__ import annotations

import sys

from bmp.experiments.member3_m3_2 import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
