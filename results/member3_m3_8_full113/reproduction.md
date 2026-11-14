# M3.8 Full 113/113 Reproduction Guide

```bash
python scripts/acquire_benchmark.py --verify-only || python scripts/acquire_benchmark.py
python scripts/run_member3_m3_8.py --config configs/member3_m3_8.toml --plots
pytest -vv tests/test_member3_full113_m3_8.py
```
