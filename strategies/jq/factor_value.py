"""
因子增强选股策略 — 聚宽格式。因子综合得分 + 股息率双层筛选。

与 caimadama.py 的区别：选股核心用因子合成得分（IC 导向）替代纯股息率+小市值逻辑。
所有 API 由引擎注入，代码零 import。

跑法：
  .venv/bin/python scripts/run_backtest.py --strategy factor_value --start 20260101 --end 20260717
"""

# 注入名（聚宽同款，零 import）：
# initialize / g / log / run_daily / order_target_value / set_benchmark / set_order_cost / OrderCost
# FixedSlippage / set_slippage / get_current_data / get_all_securities / get_dividend_map


def initialize(context):
    """盘前选股：因子得分 + 基本面过滤 → 最小市值 top N。"""
    g.stock_num = 5
    g.hold_list = []
    g.no_trading_today_signal = False

    set_benchmark('000300.XSHG')
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003,
                             close_commission=0.0003, min_commission=0), type='stock')
    set_slippage(FixedSlippage(fixed=0.0))

    run_daily(prepare_stock_list, time='9:05')
    run_daily(my_trade, time='9:31')
    if not context.run_params.get('parity_mode'):
        run_daily(check_limit_open, time='14:50')


def prepare_stock_list(context):
    """因子增强选股：
    1. get_all_securities → 当天可交易全量
    2. current_data 过滤停牌/ST/涨跌停/股价>9
    3. 因子综合得分 前 25%
    4. 股息率过滤（同原版 caimadama）
    5. 最小市值 top N
    """
    g.no_trading_today_signal = False
    prev_td = context.previous_date
    current_data = get_current_data()
    securities = get_all_securities(types=['stock'], date=prev_td)

    # 排雷候选
    candidates = []  # (code, price, total_mv)
    for sec_code in securities.index:
        code = sec_code.split('.')[0]
        c = current_data[code]
        if c.paused or c.is_st:
            continue
        price = c.last_price
        if not price or price <= 0 or price >= 9:
            continue
        chg = c.prev_change_pct
        if chg is None or chg <= -9.5 or chg >= 9.5:
            continue
        mv = c.total_mv
        if mv is None:
            continue
        candidates.append((code, price, mv))

    if not candidates:
        g.hold_list = []
        g.no_trading_today_signal = True
        return

    # ── 因子得分排名（裁到前 25%）──
    try:
        from engine.factor_scorer import score_snapshot
        scorer = score_snapshot(target_date=prev_td, top_n=1000)
        factor_score = dict(zip(scorer.scores.index, scorer.scores["score"]))
    except Exception:
        log.warning("因子评分不可用，退回到原版股息率逻辑")
        factor_score = {}

    if factor_score:
        candidates = [(c, p, m) for c, p, m in candidates
                      if c in factor_score]
        if len(candidates) > 20:
            top_k = max(10, int(len(candidates) * 0.25))
            # 得分降序 → 取前 top_k 只高分股
            candidates.sort(key=lambda x: factor_score.get(x[0], 0), reverse=True)
            candidates = candidates[:top_k]

    if not candidates:
        g.hold_list = []
        g.no_trading_today_signal = True
        return

    # ── 股息率过滤（同原版，兜底）──
    div_map = get_dividend_map(prev_td)
    if div_map and len(candidates) > 20:
        scored = [(code, price, mv, div_map.get(code, 0.0) / price)
                  for code, price, mv in candidates]
        top_k = max(10, int(len(scored) * 0.25))
        scored.sort(key=lambda x: x[3], reverse=True)
        candidates = [(c, p, m) for c, p, m, _ in scored[:top_k]]

    # ── 最小市值 top N ──
    candidates.sort(key=lambda x: x[2])
    g.hold_list = [c for c, _p, _m in candidates[:g.stock_num]]


def my_trade(context):
    """开盘调仓：等权买入目标。"""
    if g.no_trading_today_signal:
        return
    target = g.hold_list
    for code in list(context.portfolio.positions):
        if code not in target:
            order_target_value(code, 0)
    per_position = context.portfolio.total_value / g.stock_num
    for code in target:
        if code not in context.portfolio.positions:
            order_target_value(code, per_position)


def check_limit_open(context):
    """盘中 14:50 涨停开板减半仓（同 caimadama）。"""
    current_data = get_current_data()
    for code in list(context.portfolio.positions):
        pos = context.portfolio.positions.get(code)
        if pos is None or pos.closeable_amount < 100:
            continue
        c = current_data[code]
        if c.pre_close <= 0 or c.last_price <= 0 or c.day_open <= 0:
            continue
        open_ratio = (c.day_open - c.pre_close) / c.pre_close
        now_ratio = (c.last_price - c.pre_close) / c.pre_close
        if 0.05 < open_ratio < 0.098 and now_ratio < 0.035:
            order_target_value(code, pos.value / 2)
            log.info(f"[{code}] 高开回落，减半仓")
