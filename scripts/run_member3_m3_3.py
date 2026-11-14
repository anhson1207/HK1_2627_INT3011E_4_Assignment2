"""Entrypoint for the Phase M3.3 CP-SAT & IBM CP Optimizer controlled benchmark."""

from __future__ import annotations

import sys

from bmp.experiments.member3_m3_3 import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
