# Leader Phase L9 Full 113/113 Reproduction Guide

```bash
.venv/bin/python scripts/acquire_benchmark.py --max-instances 113
.venv/bin/python scripts/run_leader_l9.py --config configs/leader_l9_full113.toml --plots
.venv/bin/python -m pytest -p no:cacheprovider -vv tests/sat/test_leader_l9_full113.py
```
