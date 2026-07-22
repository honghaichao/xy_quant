# xy_quant

2026-07-14 | 99 tables | data: 2020-01 ~ 2026-07-14

daily_bar 7.7M | daily_basic 7.7M | adj_factor 7.9M | minute_bar 77m | signals 5.5K

modules: ✅ signals ✅ backtest ✅ strategies ✅ agent ✅ web ✅ trading ✅ review

```bash
PYTHONPATH=. TUSHARE_TOKEN=xxx .venv/bin/python scripts/backfill_day.py --trade-date YYYY-MM-DD
PYTHONPATH=. .venv/bin/python scripts/run_signal_scan.py --date YYYYMMDD
PYTHONPATH=. .venv/bin/python web/app.py
```
