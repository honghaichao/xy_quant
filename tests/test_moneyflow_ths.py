from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tushare as ts

from config.settings import settings


def main() -> None:
    token = settings.tushare_token
    if not token:
        raise RuntimeError("Tushare token is empty")
    ts.set_token(token)
    pro = ts.pro_api()
    df = pro.moneyflow_ths(trade_date="20260518")
    print(
        json.dumps(
            {
                "rows": int(len(df)),
                "columns": list(df.columns),
                "head": df.head(3).to_dict(orient="records"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
