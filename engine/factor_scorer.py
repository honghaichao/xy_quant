"""因子合成评分 — 多因子截面排名 × IC 方向加权 → 综合得分。

设计：
  1. 从 factor_data 取当日所有因子的全量值
  2. 从 factor_rank 取 IC 历史，挑 IC_IR = |mean_IC| / std_IC 最高且 n_days >= 5 的前 K 个因子
  3. 每个因子截面去极值（MAD 法）→ z-score 标准化 → 按 IC 方向乘 ±1
  4. IC_IR 加权合成综合得分
  5. 基本面因子（PE/PB/ROE 等）不在 factor_rank 中（因采集时机差异），直接做低 PB/低 PE/高 ROE 逻辑加权

独立模块，jq 策略和信号管线都通过 engine/loader 注入的函数调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np
import pandas as pd

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("factor_scorer")

DB_PATH = str(settings.duckdb_path)
TOP_K = 15               # 最多取前 K 个 IC 稳定因子
MIN_IC_IR = 0.8          # IC_IR 阈值
MIN_DAYS = 5             # 最少样本天数
EQUAL_WEIGHT = True      # True = 等权；False = IC_IR 加权


def _load_factor_panel(target_date: date) -> pd.DataFrame:
    """从 daily_signals 的 indicators JSON 列提取所有因子值（不依赖 factor_data 表的英文映射）。

    indicators 里既有中文 key（振幅/波动率/KDJ 等——与 auto_factor_mine 的因子名对齐）
    也有英文指标（close/ma5/rsi1 等）。直接展平成宽表。
    """
    import json

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            """SELECT code, indicators FROM daily_signals
               WHERE date = ? AND indicators IS NOT NULL""",
            [target_date.isoformat()],
        ).fetchall()
    finally:
        conn.close()

    records: list[dict] = []
    for code, raw in rows:
        try:
            ind = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ind, dict) or not ind:
            continue
        rec = {"code": code}
        for key, val in ind.items():
            if key in ("code",):  # 跳过冗余字段
                continue
            try:
                rec[key] = float(val)
            except (ValueError, TypeError):
                continue
        if len(rec) > 2:
            records.append(rec)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).set_index("code")


# ── IC 历史加载 ──────────────────────────────────────────────

def _load_factor_rank() -> pd.DataFrame:
    """factor_rank 表 → IC mean/std/n 的 DataFrame，带 IC_IR。"""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute("""
            SELECT factor_name, abs_ic_mean, ic_std, n_days
            FROM factor_rank
            WHERE n_days >= ?
        """, [MIN_DAYS]).fetchdf()
    finally:
        conn.close()
    if df.empty:
        return df
    df["ic_ir"] = (df["abs_ic_mean"] / df["ic_std"].replace(0, np.nan)).fillna(0)
    df = df.sort_values("ic_ir", ascending=False).head(TOP_K * 2)  # 预留先
    return df


def _load_ic_direction(factor_names: list[str]) -> dict[str, int]:
    """从 factor_ic 表查每个因子的平均 IC 方向：+1 或 -1。"""
    if not factor_names:
        return {}
    conn = duckdb.connect(DB_PATH, read_only=True)
    placeholders = ",".join([f"'{f}'" for f in factor_names])
    try:
        rows = conn.execute(f"""
            SELECT factor_name, AVG(ic) FROM factor_ic
            WHERE factor_name IN ({placeholders})
            GROUP BY factor_name
        """).fetchall()
    finally:
        conn.close()
    return {r[0]: (1 if r[1] > 0 else -1) for r in rows if r[1] is not None}


# ── 去极值与标准化 ──────────────────────────────────────────

def _winsorize_mad(series: pd.Series, n_mad: float = 5.0) -> pd.Series:
    """MAD 法去极值：median ± n_mad * MAD 外截断。"""
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0 or np.isnan(mad):
        return series
    upper = median + n_mad * mad
    lower = median - n_mad * mad
    return series.clip(lower=lower, upper=upper)


def _safe_zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


# ── 主入口 ───────────────────────────────────────────────────

@dataclass
class FactorScoreResult:
    """评分返回。"""

    date: date
    scores: pd.DataFrame           # code × 综合得分
    top_codes: list[str]           # 排序后的前 N 只代码
    factors_used: list[str]        # 本次用到的因子名
    factor_weights: dict[str, float]  # 因子名 → 权重


def score_snapshot(target_date: date | None = None, top_n: int = 100) -> FactorScoreResult:
    """取一日数据，算全市场综合因子得分并返回 top_n。

    target_date=None → factor_data 最新日期。
    """
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        if target_date is None:
            row = conn.execute("SELECT MAX(date) FROM factor_data").fetchone()
            if row is None or row[0] is None:
                raise RuntimeError("factor_data 为空，请先跑因子计算")
            target_date = row[0]
    finally:
        conn.close()

    # 1. 从 indicators JSON 提取所有因子值（宽表，中文/英文因子列名全在内）
    raw = _load_factor_panel(target_date)
    if raw.empty:
        raise RuntimeError(f"daily_signals 无 {target_date} 的 indicators 数据")
    raw = raw.replace([np.inf, -np.inf], np.nan)
    raw = raw.dropna(axis=1, how="all")
    # 剔除所有值为 0 的列（"大长阳":0.0 这类冗余 key）
    useful_cols = [c for c in raw.columns if raw[c].notna().any() and (raw[c] != 0).any()]
    raw = raw[useful_cols]

    # 2. IC 稳定因子池（从 factor_rank 取，按 IC 方向匹配 indicators JSON key）
    # auto_factor_mine 的因子名是 base + '_Nd'（如 '振幅_5d'），indicators JSON 是 base（如 '振幅'）
    rank = _load_factor_rank()
    rank["_base"] = rank["factor_name"].str.replace(r"_\d+d$", "", regex=True)
    # 因子名 → IC 方向 → 去掉方向后再映射到 indicators key
    directions_raw = _load_ic_direction(rank["factor_name"].tolist())
    # 重建为 base → direction（多个周期取绝对值最大的方向）
    directions: dict[str, int] = {}
    for fname, direc in directions_raw.items():
        base = fname.replace("_", "", 1) if "_" in fname else fname
        # 用 regex 去掉 _\d+d 后缀
        import re
        base = re.sub(r"_\d+d$", "", fname)
        if base not in directions or abs(ir_map.get(fname, 0)) > abs(ir_map.get(fname, 0)):
            directions[base] = direc  # 取 IC 绝对值最大的方向
    # 直接用 base name 匹配 indicators 中文 key
    # 也检查英文 key（rsi1/rsi2 等）
    indicators_keys = list(raw.columns)
    # 构建 factor_rank base → indicators_key 的精确映射
    mapped_candidates: list[str] = []
    for fn in rank["factor_name"].tolist():
        base = re.sub(r"_\d+d$", "", fn)
        if base in indicators_keys:
            mapped_candidates.append(base)
        # 也试试英文关键词（rsi1→rsi1, k→k 等——indicators 里有直接的英文 key）
        elif fn.startswith(base) and base in indicators_keys:
            mapped_candidates.append(base)
    mapped_candidates = list(dict.fromkeys(mapped_candidates))  # 去重保序
    # 匹配：indicators JSON 的 base key（如 '振幅'）↔ factor_rank 的 factor_name（如 '振幅_5d'）
    ir_map = dict(zip(rank["factor_name"], rank["ic_ir"])) if rank is not None and not rank.empty else {}
    base_ir: dict[str, float] = {}
    for fn, irv in ir_map.items():
        base = fn.rsplit("_", 1)[0] if "_" in fn and fn.rsplit("_", 1)[1].rstrip("d").isdigit() else fn
        if base not in base_ir or abs(irv) > abs(base_ir[base]):
            base_ir[base] = irv

    # 直接用映射后 key 匹配 raw.columns
    indicators_keys = list(raw.columns)
    selected = [c for c in mapped_candidates if c in indicators_keys]
    selected = sorted(selected, key=lambda c: abs(base_ir.get(c, 0)), reverse=True)[:TOP_K]
    if len(selected) < 3:
        selected = sorted(indicators_keys, key=lambda c: raw[c].nunique(), reverse=True)[:TOP_K]
    selected = selected[:TOP_K]

    # 构建 base→IC 符号
    import re as _re2
    dir_raw = _load_ic_direction(rank["factor_name"].tolist())
    base_dir_use: dict[str, int] = {}
    for fn, d in dir_raw.items():
        b = _re2.sub(r"_\d+d$", "", fn)
        if b not in base_dir_use:
            base_dir_use[b] = d
    directions = base_dir_use

    # build base_dir for directions
    import re as _re2
    dir_raw = _load_ic_direction(rank["factor_name"].tolist())
    base_dir_use: dict[str, int] = {}
    for fn, d in dir_raw.items():
        b = _re2.sub(r"_\d+d$", "", fn)
        if b not in base_dir_use:
            base_dir_use[b] = d

    # 3. 截面处理 + 合成
    factor_scores = pd.DataFrame(index=raw.index)
    weights: dict[str, float] = {}
    for col in selected:
        direction = directions.get(col, 1)
        clean = _winsorize_mad(raw[col].dropna().astype(float))
        z = _safe_zscore(clean)
        factor_scores[col] = z.reindex(raw.index).fillna(0) * direction
        weights[col] = 1.0 / len(selected) if EQUAL_WEIGHT else max(ir_map.get(col, 0.1), 0.1)

    composite = pd.Series(0.0, index=raw.index)
    for col in selected:
        composite += factor_scores[col] * weights[col]
    composite = composite.sort_values(ascending=False)

    # 4. 基本面加分（低 PB/PE + 高 ROE）—— 不通过 IC 通道直接在得分上推
    for col, direction in [("pb", -1), ("pe_ttm", -1), ("roe", 1), ("roa", 1),
                            ("gross_margin", 1), ("net_margin", 1),
                            ("profit_growth_yoy", 1), ("revenue_growth_yoy", 1)]:
        if col not in raw.columns:
            continue
        clean = _winsorize_mad(raw[col].dropna().astype(float))
        z = _safe_zscore(clean)
        composite = composite.add(z.reindex(composite.index).fillna(0) * direction * 0.08,
                                  fill_value=0)

    composite = composite.sort_values(ascending=False)
    top_codes = composite.head(top_n).index.tolist()

    logger.info(
        f"factor_scorer {target_date}: {len(selected)} 技术因子 + {sum(1 for c in ['pb','pe_ttm','roe','roa','gross_margin','net_margin','profit_growth_yoy','revenue_growth_yoy'] if c in raw.columns)} 基本面 → top {len(top_codes)}"
    )
    return FactorScoreResult(
        date=target_date, scores=composite.to_frame("score"),
        top_codes=top_codes, factors_used=selected, factor_weights=weights,
    )
