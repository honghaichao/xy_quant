# -*- coding: utf-8 -*-
"""
LightGBM 滚动训练多因子小市值策略
原策略：https://www.joinquant.com/post/75981
作者：夹头宝典（原版）

本文件为纯聚宽策略代码。所有本地数据适配在 jq_adapter/ 中完成，
策略代码不做任何平台判断。
"""

import numpy as np
import pandas as pd
import warnings
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore")

# 优先导入 LightGBM，若失败则回退到 sklearn GBDT
try:
    import lightgbm as lgb
    LGBM_AVAILABLE = True
except ImportError:
    LGBM_AVAILABLE = False
    from sklearn.ensemble import GradientBoostingClassifier


# ====================================================================
# 参数配置区
# ====================================================================
class Config:
    # ---------- 基础 ----------
    BENCHMARK = '000905.XSHG'
    STOCK_NUM = 10
    MARKET_CAP_LIMIT = 1e10                  # 100亿
    MIN_DAILY_AMOUNT = 2e7                   # 日成交额门槛 2000万

    # ---------- 训练 ----------
    TRAIN_YEARS = 3                         # 原版用 3 年训练数据
    SAMPLE_INTERVAL = 20                     # 每个月取1个快照
    HIST_MODELS_KEEP = 3
    MAX_SAMPLE_DAYS_PER_SNAPSHOT = 800

    # ---------- 标签 ----------
    LABEL_POS_LOW = 0.70
    LABEL_POS_HIGH = 0.95
    LABEL_NEG_LOW = 0.05
    LABEL_NEG_HIGH = 0.30

    # ---------- 样本加权 ----------
    SAMPLE_DECAY = 0.3

    # ---------- 模型 ----------
    LGB_PARAMS = {
        'objective': 'binary',
        'boosting_type': 'gbdt',
        'learning_rate': 0.01,
        'num_leaves': 31,
        'max_depth': -1,
        'min_child_samples': 20,
        'subsample': 0.4,
        'subsample_freq': 1,
        'colsample_bytree': 0.6,
        'reg_alpha': 0.1,
        'reg_lambda': 0.5,
        'n_estimators': 50,
        'random_state': 42,
        'verbosity': -1,
        'n_jobs': -1,
    }
    EARLY_STOPPING_ROUNDS = 30
    VALIDATION_FRAC = 0.2

    # ---------- 选股 ----------
    CANDIDATE_TOP_FRAC = 0.3
    MAX_PER_INDUSTRY = 3
    HOLDING_BONUS = 0.02

    # ---------- 风控 ----------
    STOP_LOSS = -0.15
    MAX_DRAWDOWN_SOFT = -0.20
    MAX_DRAWDOWN_HARD = -0.25
    MA_SHORT = 20
    MA_LONG = 60
    MARKET_INDEX = '000300.XSHG'


# ====================================================================
# 辅助函数
# ====================================================================

def filter_kcbj_stock(stock_list):
    """剔除科创(68)、北交(8、4)"""
    return [s for s in stock_list
            if not (s.startswith('4') or s.startswith('8') or s.startswith('68'))]


def get_small_cap_stocks(stock_list, date, cap_limit=Config.MARKET_CAP_LIMIT):
    """筛选市值 < cap_limit 的小票"""
    if not stock_list:
        return []
    result = []
    for code in stock_list:
        # 标准化代码（含 .SZ/.SH 后缀）
        norm = code if '.' in code else (code + ('.SH' if code.startswith('6') else '.SZ'))
        result.append(norm)
    if not result:
        return []

    df = get_fundamentals(
        query(
            valuation.code,
            valuation.pe_ratio,
            valuation.pb_ratio,
            valuation.ps_ratio,
            valuation.market_cap,
            valuation.turnover_ratio,
        ).filter(
            valuation.code.in_(result)
        ), date=date
    )
    if df.empty or 'market_cap' not in df.columns:
        return []

    df = df.set_index("code")
    small = df[df['market_cap'].notna() & (df['market_cap'] < cap_limit)]
    return small.index.tolist()


# ====================================================================
# 因子数据获取
# ====================================================================

def get_all_factor_data(securities_list, date):
    """统一的因子数据获取:
      1. jqfactor（聚宽因子）
      2. valuation（估值+换手）
      3. indicator（质量+成长）
      4. 自定义计算 — 动量(MOM系列) + VOL20 + RSI12
    返回合并后的 DataFrame
    """
    if not securities_list:
        return pd.DataFrame()

    df_all = pd.DataFrame(index=securities_list)

    # ========== 1. jqfactor ==========
    try:
        jq_data = get_factor_values(
            securities=securities_list,
            factors=g.jqfactor_list,
            count=1,
            end_date=date)
        for f in jq_data.keys():
            df_all[f] = jq_data[f].iloc[0, :]
    except Exception as e:
        log.warning("jqfactor 获取失败: %s" % str(e)[:80])

    # ========== 2. valuation 估值数据（PE/PB/PS/换手率） ==========
    try:
        fund_val = get_fundamentals(
            query(
                valuation.code,
                valuation.pe_ratio,
                valuation.pb_ratio,
                valuation.ps_ratio,
                valuation.market_cap,
                valuation.turnover_ratio,
            ).filter(
                valuation.code.in_(securities_list)
            ), date=date
        )
        if not fund_val.empty:
            fund_val = fund_val.set_index("code")
            for col in g.fund_val_cols:
                if col in fund_val.columns:
                    df_all[col] = fund_val[col].astype(float)
    except Exception as e:
        log.warning("valuation 估值数据获取失败: %s" % str(e)[:80])

    # ========== 3. indicator 质量数据（ROE/ROA/毛利/利润增速/营收增速） ==========
    try:
        fund_ind = get_fundamentals(
            query(
                indicator.code,
                indicator.roe,
                indicator.roa,
                indicator.gross_profit_margin,
                indicator.inc_net_profit_year_on_year,
                indicator.inc_revenue_year_on_year,
            ).filter(
                indicator.code.in_(securities_list)
            ), date=date
        )
        if not fund_ind.empty:
            fund_ind = fund_ind.set_index("code")
            for col in g.fund_ind_cols:
                if col in fund_ind.columns:
                    df_all[col] = fund_ind[col].astype(float)
    except Exception as e:
        log.warning("indicator 获取失败: %s" % str(e)[:80])

    # ========== 4. 自定义计算：动量 + VOL20 + RSI12 ==========
    try:
        price_df = get_price(
            securities_list,
            end_date=date,
            count=140,
            frequency='daily',
            fields=['close'],
            panel=False,
            fill_paused=False)
        if price_df is not None and not price_df.empty:
            if 'trade_date' in price_df.columns:
                price_df = price_df.sort_values(['code', 'trade_date'])

            metrics_rows = []
            for stock, group in price_df.groupby('code'):
                closes = group['close'].values
                n_len = len(closes)
                if n_len < 15:
                    continue
                row = {}
                if n_len >= 14:
                    diffs14 = np.diff(closes[-14:])
                    gains = np.maximum(diffs14, 0).sum() / 12
                    losses = np.abs(np.minimum(diffs14, 0)).sum() / 12
                    row['RSI12'] = 100 - 100 / (1 + gains / losses) if losses > 0 else np.nan
                if n_len >= 21:
                    seg = closes[-21:]
                    rets = np.diff(seg) / seg[:-1]
                    row['VOL20'] = np.std(rets) * np.sqrt(252)
                    row['MOM20'] = closes[-1] / closes[-21] - 1
                if n_len >= 61:
                    row['MOM60'] = closes[-1] / closes[-61] - 1
                if n_len >= 121:
                    row['MOM120'] = closes[-1] / closes[-121] - 1
                if row:
                    metrics_rows.append((stock, row))

            if metrics_rows:
                idx, rows = zip(*metrics_rows)
                computed = pd.DataFrame(list(rows), index=list(idx))
                for col in computed.columns:
                    df_all[col] = np.nan
                computed = computed.reindex(df_all.index)
                for col in computed.columns:
                    df_all[col] = computed[col]
    except Exception as e:
        log.warning("自定义因子计算失败: %s" % str(e)[:80])

    # 确保所有因子列都存在
    for col in g.all_factor_cols:
        if col not in df_all.columns:
            df_all[col] = np.nan
        else:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce')
    return df_all[g.all_factor_cols].astype(np.float64)


def get_stock_pool2(stock_list, raw_date, min_amount=Config.MIN_DAILY_AMOUNT):
    """风险过滤：非涨跌停、非停牌、非ST、非科创北交、成交额达标"""
    if not stock_list:
        return []

    # Convert datetime to date if needed
    from datetime import datetime as _dt
    date = raw_date.date() if hasattr(raw_date, 'date') and isinstance(raw_date, _dt) else raw_date

    # 确保证券当天存在
    all_stocks = get_all_securities(date=date)
    if all_stocks.empty:
        return []
    all_codes = all_stocks.index.tolist()
    stock_list = list(set(stock_list) & set(all_codes))
    if not stock_list:
        return []

    # 过滤涨跌停(±9.5%) + 停牌(vol==0)
    df_price = get_price(
        security=stock_list, frequency='daily', end_date=date, count=2,
        fields=['close', 'open', 'vol', 'pre_close'], panel=False)
    if df_price.empty:
        return []
    # 每只股票取最新的那行
    latest = df_price.sort_values('trade_date').groupby('code').tail(1)
    latest['high_limit_est'] = latest['pre_close'] * 1.10
    latest['low_limit_est'] = latest['pre_close'] * 0.90
    stock_list = latest.query(
        'close > low_limit_est and close < high_limit_est and vol > 0'
    )['code'].tolist()
    if not stock_list:
        return []

    # ST 过滤
    try:
        s_extras = get_extras(
            info='is_st', security_list=stock_list,
            end_date=date, count=1)
        if not s_extras.empty:
            st_codes = s_extras.columns[s_extras.iloc[0].values.astype(bool)].tolist()
            stock_list = [s for s in stock_list if s not in st_codes]
    except Exception:
        pass

    # 科创北交过滤
    stock_list = filter_kcbj_stock(stock_list)

    # 流动性过滤（近5日日均成交额）
    if stock_list and min_amount > 0:
        try:
            df_amount = get_price(
                stock_list, end_date=date, count=5,
                frequency='daily', fields=['money'], panel=False)
            if not df_amount.empty:
                avg_amount = df_amount.groupby('code')['money'].mean()
                liquid = avg_amount[avg_amount >= min_amount].index.tolist()
                stock_list = [s for s in stock_list if s in liquid]
        except Exception:
            pass

    return stock_list


# ====================================================================
# 因子预处理
# ====================================================================

def mad_outlier(df, n=3):
    """MAD 去极值"""
    result = df.copy()
    for col in result.columns:
        median = result[col].median()
        mad = (result[col] - median).abs().median()
        if mad == 0:
            continue
        upper = median + n * mad * 1.4826
        lower = median - n * mad * 1.4826
        result[col] = result[col].clip(lower, upper)
    return result


def neutralize_factors(df, stocks, date):
    """行业 + 市值中性化：因子值对行业哑变量 + ln(市值) 回归取残差"""
    if df.empty or len(df) < 30:
        return df
    try:
        # 获取市值（从 valuation）
        mcap_df = get_fundamentals(
            query(
                valuation.code,
                valuation.market_cap,
            ).filter(
                valuation.code.in_(list(df.index))
            ), date=date
        )
        if mcap_df.empty or 'market_cap' not in mcap_df.columns:
            return df
        mcap_df = mcap_df.set_index("code")
        mcap_df['ln_mcap'] = np.log(mcap_df['market_cap'])
        df = df.join(mcap_df['ln_mcap'], how='inner')

        # 获取行业
        try:
            ind_dict = get_industry(list(df.index), date=date)
            if ind_dict:
                industry_map = {}
                for code, info in ind_dict.items():
                    for level in ('sw_l1', 'sw_l2'):
                        if level in info:
                            industry_map[code] = info[level].get('industry_name', 'unknown')
                            break
                    if code not in industry_map:
                        industry_map[code] = 'unknown'
                ind_df = pd.DataFrame.from_dict(
                    industry_map, orient='index', columns=['industry'])
                df = df.join(ind_df, how='left')
            else:
                df['industry'] = 'unknown'
        except Exception:
            df['industry'] = 'unknown'

        df['industry'] = df['industry'].fillna('unknown')
        ind_dummies = pd.get_dummies(df['industry'], drop_first=True)
        ind_dummies.index = df.index

        X_neut = pd.concat([ind_dummies, df['ln_mcap']], axis=1).fillna(0)

        factor_cols = [c for c in df.columns if c in g.all_factor_cols]
        if not factor_cols:
            return df
        y_mat = pd.DataFrame({c: pd.to_numeric(df[c], errors='coerce') for c in factor_cols},
                             index=df.index)
        y_mat = y_mat.fillna(y_mat.median())
        mask = y_mat.notna().all(axis=1) & np.isfinite(y_mat).all(axis=1)
        if mask.sum() < 30:
            return df[g.all_factor_cols]
        X = X_neut.loc[mask].values.astype(np.float64)
        Y = y_mat.loc[mask].values.astype(np.float64)
        try:
            beta, _, _, _ = np.linalg.lstsq(X, Y, rcond=None)
            residuals = Y - X @ beta
        except np.linalg.LinAlgError:
            return df[g.all_factor_cols]
        resid_df = pd.DataFrame(residuals, index=y_mat.loc[mask].index, columns=factor_cols)
        df_neut = resid_df.reindex(df.index)
        for c in factor_cols:
            df_neut[c] = df_neut[c].fillna(df[c])
        return df_neut
    except Exception:
        return df[g.all_factor_cols]


def preprocess_factors(df, stocks, date, scaler=None, fit_scaler=False):
    """因子预处理流水线：去极值 → 中性化 → 标准化"""
    if df.empty:
        return df, scaler

    factor_cols = [c for c in df.columns if c in g.all_factor_cols]
    if not factor_cols:
        return df, scaler

    df_clean = mad_outlier(df[factor_cols], n=3)
    df_neut = neutralize_factors(df_clean, stocks, date)

    df_filled = df_neut.copy()
    numeric = df_filled.select_dtypes(include=[np.number])
    medians = numeric.median()
    numeric = numeric.fillna(medians).clip(numeric.min(), numeric.max(), axis=1)
    for c in df_filled.columns:
        if c in numeric.columns:
            df_filled[c] = numeric[c]
        else:
            df_filled[c] = pd.to_numeric(df_filled[c], errors='coerce').fillna(0).clip(lower=df_filled[c].quantile(0.01) if not pd.isna(df_filled[c].quantile(0.01)) else None)

    std_check = df_filled.std()
    if (std_check == 0).all():
        return df_filled, scaler

    if fit_scaler or scaler is None:
        scaler = StandardScaler()
        scaled = scaler.fit_transform(df_filled)
    else:
        scaled = scaler.transform(df_filled)

    df_out = pd.DataFrame(scaled, index=df_filled.index,
                           columns=df_filled.columns)
    return df_out, scaler


# ====================================================================
# 核心：滚动训练 + LightGBM
# ====================================================================

def build_train_dates(context):
    """构建训练采样日期列表"""
    cfg = Config()
    total_days = int(cfg.TRAIN_YEARS * 250)
    all_dates = get_trade_days(
        end_date=context.previous_date, count=total_days)
    all_dates = list(reversed(all_dates))
    date_list = all_dates[::cfg.SAMPLE_INTERVAL]
    date_list = list(reversed(date_list))
    return date_list


def build_label(stock_list, current_date, horizon_date):
    """计算涨跌幅标签"""
    if not stock_list:
        return None
    try:
        data_close = get_price(
            stock_list, current_date, horizon_date,
            '1d', ['close'])
        if data_close.empty:
            return None
        pchg = pd.Series(index=stock_list, dtype=float)
        for code in data_close['code'].unique():
            cdata = data_close[data_close['code'] == code].sort_values('trade_date')
            if len(cdata) >= 2:
                pchg.loc[code] = cdata['close'].iloc[-1] / cdata['close'].iloc[0] - 1
        return pchg.dropna()
    except Exception:
        return None


def create_training_samples(context):
    """滚动构建训练样本"""
    cfg = Config()
    date_list = build_train_dates(context)
    log.info(f"构建训练样本: 共{len(date_list)}个采样日")
    if len(date_list) < 3:
        log.warning("训练日期不足")
        return None, None, None

    train_data_list = []
    current_date = context.previous_date

    for i, date in enumerate(date_list[:-1]):
        if i % 3 == 0:
            log.info(f"  采样: {i+1}/{len(date_list)-1}")
        next_date = date_list[i + 1]

        S_all = get_all_securities(types=['stock'], date=date)
        if S_all.empty:
            continue
        S_all = S_all.index.tolist()
        S_all = [s for s in S_all if not (s.startswith('4') or s.startswith('8') or s.startswith('688'))]
        S_small = get_small_cap_stocks(S_all, date, cfg.MARKET_CAP_LIMIT)
        if len(S_small) > cfg.MAX_SAMPLE_DAYS_PER_SNAPSHOT:
            import random
            S_small = random.sample(S_small, cfg.MAX_SAMPLE_DAYS_PER_SNAPSHOT)
        if len(S_small) < 80:
            continue

        factor_raw = get_all_factor_data(S_small, date)
        if factor_raw.empty or len(factor_raw) < 50:
            continue

        factor_processed, _ = preprocess_factors(
            factor_raw, S_small, date, fit_scaler=True)
        if factor_processed.empty:
            continue

        pchg = build_label(S_small, date, next_date)
        if pchg is None:
            continue

        factor_processed = factor_processed.loc[
            factor_processed.index.isin(pchg.index)]
        pchg = pchg.loc[factor_processed.index]

        factor_processed['pchg'] = pchg.values
        factor_processed = factor_processed.sort_values(
            by='pchg', ascending=True)
        n = len(factor_processed)

        neg_low = int(n * cfg.LABEL_NEG_LOW)
        neg_high = int(n * cfg.LABEL_NEG_HIGH)
        pos_low = int(n * cfg.LABEL_POS_LOW)
        pos_high = int(n * cfg.LABEL_POS_HIGH)

        neg = factor_processed.iloc[neg_low:neg_high].copy()
        neg['label'] = 0
        pos = factor_processed.iloc[pos_low:pos_high].copy()
        pos['label'] = 1

        if len(neg) < 20 or len(pos) < 20:
            continue

        this_period = pd.concat([neg, pos])

        days_ago = (current_date - date).days
        weight = np.exp(-cfg.SAMPLE_DECAY * days_ago / 365)
        this_period['sample_weight'] = weight

        train_data_list.append(this_period)

    if not train_data_list:
        return None, None, None

    train_data = pd.concat(train_data_list, ignore_index=True)

    X = train_data[g.all_factor_cols].values
    y = train_data['label'].values
    sample_weights = train_data['sample_weight'].values

    return X, y, sample_weights


def train_lightgbm(X, y, sample_weights):
    """训练 LightGBM 模型（含早停）"""
    cfg = Config()
    if X is None or len(X) < 50:
        return None

    n_val = int(len(X) * cfg.VALIDATION_FRAC)
    if n_val < 20:
        n_val = min(20, len(X) // 4)
    if n_val < 1 or len(X) - n_val < 1:
        return None

    X_train, X_val = X[:-n_val], X[-n_val:]
    y_train, y_val = y[:-n_val], y[-n_val:]
    sw_train = sample_weights[:-n_val] if sample_weights is not None else None
    sw_val = sample_weights[-n_val:] if sample_weights is not None else None

    params = cfg.LGB_PARAMS.copy()
    n_estimators = params.pop('n_estimators')

    if LGBM_AVAILABLE:
        model = lgb.LGBMClassifier(**params, n_estimators=n_estimators)
        fit_kwargs = dict(
            sample_weight=sw_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(cfg.EARLY_STOPPING_ROUNDS)],
        )
        try:
            fit_kwargs['eval_sample_weight'] = [sw_val]
        except Exception:
            pass
        model.fit(X_train, y_train, **fit_kwargs)
    else:
        model = GradientBoostingClassifier(
            learning_rate=0.01, max_depth=10,
            min_samples_split=20, n_estimators=n_estimators,
            subsample=0.4, random_state=42)
        model.fit(X_train, y_train, sample_weight=sw_train)

    return model


# ====================================================================
# 市场状态判断
# ====================================================================

def check_market_regime(context):
    """判断市场状态：MA20 < MA60 → 偏熊"""
    cfg = Config()
    try:
        df = get_price(
            cfg.MARKET_INDEX,
            end_date=context.previous_date,
            count=cfg.MA_LONG + 10,
            frequency='daily',
            fields=['close'],
            panel=False)
        if df is None or df.empty:
            g.market_bearish = False
            return
        closes = df['close'].values
        ma_short = np.mean(closes[-cfg.MA_SHORT:])
        ma_long = np.mean(closes[-cfg.MA_LONG:])
        g.market_bearish = ma_short < ma_long
    except Exception:
        g.market_bearish = False


# ====================================================================
# 选股
# ====================================================================

def get_stock_list(context):
    """主选股：训练 → 预测 → 筛选"""
    cfg = Config()
    yesterday = context.previous_date

    # ---------- 1. 训练 ----------
    log.info("开始滚动训练...")
    log.info("开始创建训练样本...")
    X, y, sw = create_training_samples(context)
    if X is not None:
        log.info("训练数据: X=%s, y=%s, 正样本=%.0f%%, 负样本=%.0f%%" % (
            str(X.shape), str(y.shape),
            y.mean() * 100, (1 - y.mean()) * 100))
    log.info("开始训练 LightGBM...")
    model = train_lightgbm(X, y, sw)
    log.info("LightGBM 训练完成")
    if model is None:
        log.warning("模型训练失败，本次不交易")
        return []

    g.hist_models.append(model)
    if len(g.hist_models) > cfg.HIST_MODELS_KEEP:
        g.hist_models = g.hist_models[-cfg.HIST_MODELS_KEEP:]

    # ---------- 2. 候选池 ----------
    initial_list = get_all_securities(types=['stock'], date=yesterday)
    if initial_list.empty:
        return []
    initial_list = initial_list.index.tolist()
    initial_list = filter_kcbj_stock(initial_list)
    small_cap_list = get_small_cap_stocks(
        initial_list, yesterday, cfg.MARKET_CAP_LIMIT)
    if not small_cap_list:
        return []

    log.info(f"风控过滤前: {len(small_cap_list)} 只候选")
    small_cap_list = get_stock_pool2(small_cap_list, context.current_dt)
    log.info(f"风控过滤后: {len(small_cap_list)} 只候选")
    if not small_cap_list:
        return []

    # ---------- 3. 预处理预测 ----------
    log.info(f"获取因子数据: {len(small_cap_list)} 只股票")
    df = get_all_factor_data(small_cap_list, yesterday)
    log.info(f"因子数据获取完成: {len(df)} 行")
    if df.empty:
        return []

    df_processed, _ = preprocess_factors(
        df, small_cap_list, yesterday, fit_scaler=True)
    X_test = df_processed.values

    # ---------- 4. 模型集成预测 ----------
    all_probas = []
    for m in g.hist_models:
        try:
            proba = m.predict_proba(X_test)[:, 1]
            all_probas.append(proba)
        except Exception:
            pass
    if not all_probas:
        return []

    y_pred = np.mean(all_probas, axis=0)
    df['total_score'] = y_pred

    # ---------- 5. 持仓加分 ----------
    for stock in g.hold_list:
        if stock in df.index:
            df.loc[stock, 'total_score'] += cfg.HOLDING_BONUS

    df = df.sort_values(by='total_score', ascending=False)

    # ---------- 6. 取前 N% 候选 ----------
    lst = df.index.tolist()
    N_top = max(cfg.STOCK_NUM * 3, int(len(lst) * cfg.CANDIDATE_TOP_FRAC))
    lst = lst[:N_top]

    # ---------- 7. 行业分散化 ----------
    try:
        industry_map = {}
        raw_industry_map = get_industry(lst, date=yesterday)
        if raw_industry_map:
            for code, info in raw_industry_map.items():
                for level in ('sw_l1', 'sw_l2'):
                    if level in info:
                        industry_map[code] = info[level].get('industry_name', 'unknown')
                        break
                if code not in industry_map:
                    industry_map[code] = 'unknown'
    except Exception:
        industry_map = {s: 'unknown' for s in lst}

    industry_count = {}
    target_list = []
    scored_list = df.loc[lst].sort_values(
        'total_score', ascending=False).index.tolist()

    for stock in scored_list:
        if len(target_list) >= cfg.STOCK_NUM:
            break
        ind = industry_map.get(stock, 'unknown')
        if industry_count.get(ind, 0) >= cfg.MAX_PER_INDUSTRY:
            continue
        target_list.append(stock)
        industry_count[ind] = industry_count.get(ind, 0) + 1

    # 不够则从剩余按市值补
    if len(target_list) < cfg.STOCK_NUM:
        mcap_df = get_fundamentals(
            query(
                valuation.code,
                valuation.market_cap,
            ).filter(
                valuation.code.in_(lst)
            ), date=yesterday
        )
        if not mcap_df.empty and 'market_cap' in mcap_df.columns:
            mcap_df = mcap_df.set_index("code")
            remaining = [s for s in lst
                         if s not in target_list and s in mcap_df.index]
            if remaining:
                df_rem = mcap_df.loc[remaining].sort_values('market_cap')
                extra = df_rem.index.tolist()[
                    :cfg.STOCK_NUM - len(target_list)]
                target_list.extend(extra)

    return target_list


# ====================================================================
# 调仓与交易
# ====================================================================

def prepare_stock_list(context):
    """记录持仓和昨日涨停股"""
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    if g.hold_list:
        df = get_price(
            g.hold_list, end_date=context.previous_date,
            frequency='daily', fields=['close', 'pre_close'],
            count=1, panel=False, fill_paused=False)
        if 'pre_close' in df.columns:
            df['high_limit_est'] = df['pre_close'] * 1.10
            df = df[df['close'] >= df['high_limit_est'] * 0.995]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []


def calculate_position_size(context, target_num):
    """计算每只股票的目标仓位金额（考虑风控）"""
    cfg = Config()

    if g.market_bearish:
        available_cash = context.portfolio.total_value * 0.5
    else:
        available_cash = context.portfolio.total_value

    if g.strategy_peak is None:
        g.strategy_peak = context.portfolio.total_value
    else:
        g.strategy_peak = max(g.strategy_peak, context.portfolio.total_value)

    drawdown = (context.portfolio.total_value - g.strategy_peak) / g.strategy_peak
    if drawdown < cfg.MAX_DRAWDOWN_HARD:
        log.warning("🚨 回撤 %.1f%% 超过硬止损线，清仓！" % (drawdown * 100))
        return 0
    elif drawdown < cfg.MAX_DRAWDOWN_SOFT:
        log.warning("⚠️ 回撤 %.1f%% 超过软止损线，减半仓" % (drawdown * 100))
        available_cash *= 0.5

    if target_num <= 0:
        return 0
    return available_cash / target_num


def weekly_adjustment(context):
    """月频调仓"""
    cfg = Config()
    target_list = get_stock_list(context)

    g.strategy_peak = max(g.strategy_peak or 0, context.portfolio.total_value)
    drawdown = (context.portfolio.total_value - g.strategy_peak) / (
        g.strategy_peak or 1)
    if drawdown < cfg.MAX_DRAWDOWN_HARD:
        for stock in list(context.portfolio.positions.keys()):
            close_position(context.portfolio.positions[stock])
        log.warning("硬止损触发，已清仓")
        return

    # 卖出不在目标列表的股票（非涨停锁死）
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.yesterday_HL_list):
            position = context.portfolio.positions[stock]
            close_position(position)

    # 买入
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = calculate_position_size(context, target_num)
        if value <= 0:
            return
        current_positions = set(context.portfolio.positions.keys())
        for stock in target_list:
            if stock not in current_positions:
                if open_position(stock, value):
                    current_positions = set(context.portfolio.positions.keys())
                    if len(current_positions) >= target_num:
                        break


def check_limit_up(context):
    """涨停打开则卖出（批量查询）"""
    if not g.yesterday_HL_list:
        return
    hl_list = g.yesterday_HL_list

    price_map = {}
    try:
        prices_df = get_price(
            hl_list, end_date=context.current_dt, frequency='daily',
            fields=['close', 'pre_close'],
            count=1, panel=False, fill_paused=True)
        if prices_df is not None and not prices_df.empty:
            for _, row in prices_df.iterrows():
                code = row.get('code', '')
                price_map[code] = {
                    'close': float(row['close']),
                    'pre_close': float(row.get('pre_close', row['close'])),
                }
    except Exception:
        pass

    for stock in hl_list:
        info = price_map.get(stock)
        if info is None:
            continue
        limit_up = info['pre_close'] * 1.10
        if info['close'] < limit_up:
            log.info("[%s] 涨停打开，卖出" % stock)
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("[%s] 涨停，继续持有" % stock)


def check_stop_loss(context):
    """个股止损检查（批量查询 T-1 日终 close）"""
    cfg = Config()
    pos_keys = list(context.portfolio.positions.keys())
    active = [s for s in pos_keys if context.portfolio.positions[s].total_amount > 0]
    if not active:
        return

    price_map = {}
    try:
        prices_df = get_price(
            active,
            end_date=context.current_dt,
            frequency='daily',
            fields=['close'],
            count=1,
            panel=False,
            fill_paused=True)
        if prices_df is not None and not prices_df.empty:
            for _, row in prices_df.iterrows():
                code = row.get('code', '')
                close_v = float(row['close']) if pd.notna(row.get('close')) else None
                if close_v:
                    price_map[code] = close_v
    except Exception:
        pass

    for stock in active:
        position = context.portfolio.positions[stock]
        avg_cost = position.avg_cost
        if not avg_cost:
            continue
        current_price = price_map.get(stock)
        if current_price is None and hasattr(position, 'price'):
            current_price = position.price
        if current_price:
            pnl_pct = (current_price - avg_cost) / avg_cost
            if pnl_pct < cfg.STOP_LOSS:
                log.info("🛑 [%s] 止损 %.1f%%，卖出" % (stock, pnl_pct * 100))
                close_position(position)


# ====================================================================
# 交易执行
# ====================================================================

def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % security)
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


def open_position(security, value):
    order = order_target_value_(security, value)
    if order is not None:
        if isinstance(order, dict):
            return order.get("shares", 0) > 0
        return order.filled > 0 if hasattr(order, 'filled') else bool(order)
    return False


def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)
    if order is not None:
        if isinstance(order, dict):
            return True
        return True
    return False


# ====================================================================
# 初始化（JQ 引擎入口）
# ====================================================================

def initialize(context):
    cfg = Config()

    set_benchmark(cfg.BENCHMARK)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0.003))
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        min_commission=5), type='stock')
    log.set_level('order', 'error')

    # ----- 全局变量 -----
    g.no_trading_today_signal = False
    g.stock_num = cfg.STOCK_NUM
    g.hold_list = []
    g.yesterday_HL_list = []
    g.hist_models = []
    g.strategy_peak = None
    g.market_bearish = False

    # ----- 因子配置 -----
    # ① jqfactor（仅 4 个——原版已验证的因子名）
    g.jqfactor_list = [
        'financial_liability',
        'VOL240',
        'administration_expense_ttm',
        'liquidity',
    ]

    # ② fundamentals：valuation 表（估值 + 换手）
    g.fund_val_cols = ['pe_ratio', 'pb_ratio', 'ps_ratio', 'turnover_ratio']

    # ③ fundamentals：indicator 表（质量 + 成长）
    g.fund_ind_cols = ['roe', 'roa', 'gross_profit_margin',
                       'inc_net_profit_year_on_year',
                       'inc_revenue_year_on_year']

    # ④ 自定义计算（基于 get_price）：动量 + 波动 + RSI
    g.computed_cols = ['MOM20', 'MOM60', 'MOM120', 'VOL20', 'RSI12']

    # ----- 最终合并后的因子列名（共 18 个）-----
    g.all_factor_cols = (
        g.jqfactor_list
        + g.fund_val_cols
        + g.fund_ind_cols
        + g.computed_cols
    )

    # 跑定时任务
    run_daily(prepare_stock_list, '9:05')
    run_monthly(weekly_adjustment, 1, '9:30')
    run_daily(check_limit_up, '14:00')
    run_daily(check_stop_loss, '14:30')
    run_daily(check_market_regime, '9:35')
