from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path('/Volumes/quant-ssd/projects/xy_quant')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.source.tushare_source import TushareSource
from data.storage.pg_store import PostgresMetaStore

SUMMARY_PATH = ROOT / 'tmp' / 'backfill_members_summary.json'
TRADE_DATE = date(2026, 5, 8)
INDEX_CODES = ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH', '000905.SH', '000852.SH']

source = TushareSource()
store = PostgresMetaStore()
summary = {
    'trade_date': TRADE_DATE.isoformat(),
    'index_codes': INDEX_CODES,
    'counts': {'concept_list': 0, 'industry_list': 0, 'concept_member': 0, 'industry_member': 0, 'index_weight': 0},
    'errors': [],
}


def _normalize_concept_member(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=['concept_code', 'concept_name', 'ts_code', 'in_date', 'out_date', 'is_active'])
    normalized = frame.copy()
    if 'id' in normalized.columns and 'concept_code' not in normalized.columns:
        normalized = normalized.rename(columns={'id': 'concept_code'})
    if 'concept_code' not in normalized.columns:
        normalized['concept_code'] = None
    if 'in_date' not in normalized.columns:
        normalized['in_date'] = TRADE_DATE
    normalized['in_date'] = normalized['in_date'].fillna(TRADE_DATE)
    if 'out_date' not in normalized.columns:
        normalized['out_date'] = None
    if 'is_active' not in normalized.columns:
        normalized['is_active'] = 1
    normalized['is_active'] = normalized['is_active'].fillna(1)
    return normalized[['concept_code', 'concept_name', 'ts_code', 'in_date', 'out_date', 'is_active']]


def _normalize_industry_member(frame: pd.DataFrame, name_map: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=['industry_code', 'industry_name', 'ts_code', 'in_date', 'out_date'])
    normalized = frame.copy()
    if 'index_code' in normalized.columns and 'industry_code' not in normalized.columns:
        normalized = normalized.rename(columns={'index_code': 'industry_code'})
    if 'con_code' in normalized.columns and 'ts_code' not in normalized.columns:
        normalized = normalized.rename(columns={'con_code': 'ts_code'})
    if 'industry_name' not in normalized.columns:
        normalized['industry_name'] = normalized['industry_code'].map(name_map)
    if 'in_date' not in normalized.columns:
        normalized['in_date'] = TRADE_DATE
    normalized['in_date'] = normalized['in_date'].fillna(TRADE_DATE)
    if 'out_date' not in normalized.columns:
        normalized['out_date'] = None
    return normalized[['industry_code', 'industry_name', 'ts_code', 'in_date', 'out_date']]


try:
    concept_df = source.fetch_concept_list()
    industry_df = source.fetch_industry_list()
    summary['counts']['concept_list'] = store.upsert('concept_list', concept_df)
    summary['counts']['industry_list'] = store.upsert('industry_list', industry_df)

    concept_codes = [code for code in concept_df.get('code', []).tolist() if isinstance(code, str) and code]
    industry_codes = [code for code in industry_df.get('index_code', []).tolist() if isinstance(code, str) and code]
    industry_name_map = dict(zip(industry_df['index_code'], industry_df['industry_name'], strict=False))
    summary['concept_codes'] = len(concept_codes)
    summary['industry_codes'] = len(industry_codes)

    for idx, concept_code in enumerate(concept_codes, start=1):
        try:
            frame = _normalize_concept_member(source.fetch_concept_member(concept_code))
            summary['counts']['concept_member'] += store.upsert('concept_member', frame)
            if idx % 25 == 0:
                print(f'progress concept_member {idx}/{len(concept_codes)} code={concept_code}', flush=True)
        except Exception as exc:  # noqa: BLE001
            try:
                store.connection.rollback()
            except Exception:  # noqa: BLE001
                pass
            summary['errors'].append({'table': 'concept_member', 'code': concept_code, 'error': str(exc)})
            print(f'ERROR concept_member code={concept_code} error={exc}', flush=True)

    for idx, industry_code in enumerate(industry_codes, start=1):
        try:
            frame = _normalize_industry_member(source.fetch_industry_member(industry_code), industry_name_map)
            summary['counts']['industry_member'] += store.upsert('industry_member', frame)
            if idx % 25 == 0:
                print(f'progress industry_member {idx}/{len(industry_codes)} code={industry_code}', flush=True)
        except Exception as exc:  # noqa: BLE001
            try:
                store.connection.rollback()
            except Exception:  # noqa: BLE001
                pass
            summary['errors'].append({'table': 'industry_member', 'code': industry_code, 'error': str(exc)})
            print(f'ERROR industry_member code={industry_code} error={exc}', flush=True)

    for index_code in INDEX_CODES:
        try:
            frame = source.fetch_index_weight(index_code, trade_date=TRADE_DATE)
            summary['counts']['index_weight'] += store.upsert('index_weight', frame)
        except Exception as exc:  # noqa: BLE001
            try:
                store.connection.rollback()
            except Exception:  # noqa: BLE001
                pass
            summary['errors'].append({'table': 'index_weight', 'code': index_code, 'error': str(exc)})
            print(f'ERROR index_weight code={index_code} error={exc}', flush=True)

    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'summary_path={SUMMARY_PATH}', flush=True)
finally:
    store.close()
