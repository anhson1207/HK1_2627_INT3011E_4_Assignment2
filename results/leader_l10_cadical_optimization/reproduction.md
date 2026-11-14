# L10 reproduction

Run `.venv/bin/python scripts/run_leader_l10.py --max-batch-seconds 1500` from repo root. The campaign resumes from atomic `checkpoint_runs.json` and never writes L9 results. Then run `.venv/bin/python scripts/report_leader_l10.py`, `.venv/bin/python -m pytest -q`, `.venv/bin/python -m pip wheel . --no-deps --no-build-isolation -w /tmp/bmp-l10-dist`, and `.venv/bin/python -m bmp --help`.
