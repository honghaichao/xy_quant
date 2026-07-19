from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path('/Volumes/quant-ssd/projects/xy_quant')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.source.tushare_source import TushareSource
from data.storage.pg_store import PostgresMetaStore

summary_path = ROOT / 'tmp' / 'load_member_lists_summary.json'

source = TushareSource()
store = PostgresMetaStore()
try:
    concept_df = source.fetch_concept_list()
    industry_df = source.fetch_industry_list()
    result = {
        'concept_list_rows': store.upsert('concept_list', concept_df),
        'industry_list_rows': store.upsert('industry_list', industry_df),
        'concept_list_total': int(len(concept_df)),
        'industry_list_total': int(len(industry_df)),
    }
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'summary_path': str(summary_path), **result}, ensure_ascii=False))
finally:
    store.close()
    source = None
