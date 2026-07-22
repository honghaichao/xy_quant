"""
菜场大妈选股法 — 聚宽格式参考策略。零 import（所有 API 由引擎注入）。

选股逻辑逐条对齐 strategies/caimadama/strategy.py:52-116：
  T-1 数据、非 ST、上市日过滤、排涨跌停(±9.5%)、股价<9、股息率前 25%、最小市值 top5。

盘前 9:05 用 get_current_data() 的 T-1 视图选股（结构性无未来函数）；
9:31 开盘调仓；14:50 涨停开板检查（平价验证 run_params={'parity_mode': True} 时关闭）。
"""

# 注入名（真聚宽同款，本文件零 import）：
# initialize / g / log / run_daily / order_target_value / set_benchmark / set_order_cost
# OrderCost / FixedSlippage / set_slippage / get_current_data / get_all_securities / get_dividend_map


def initialize(context):
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
    """盘前选股：T-1 数据（current_data 盘前视图），逐条复刻原 select_stocks 过滤。"""
    g.no_trading_today_signal = False
    prev_td = context.previous_date

    securities = get_all_securities(types=['stock'], date=prev_td)
    if securities.empty:
        g.no_trading_today_signal = True
        return
    current_data = get_current_data()

    candidates = []  # (code, prev_close, total_mv)
    for sec_code in securities.index:
        code = sec_code.split('.')[0]   # 统一 6 位码（div_map/持仓/成交全链路一致）
        c = current_data[code]
        # paused（盘前=T-1 无 bar）兼顾过滤 688/920（引擎数据层已排除其 bar）
        if c.paused or c.is_st:
            continue
        price = c.last_price          # 盘前视图 = T-1 close
        if not price or price <= 0 or price >= 9:
            continue
        chg = c.prev_change_pct       # T-1 涨跌幅
        if chg is None or chg <= -9.5 or chg >= 9.5:
            continue
        if c.total_mv is None:
            continue
        candidates.append((code, price, c.total_mv))

    if not candidates:
        g.hold_list = []
        g.no_trading_today_signal = True
        return

    # 股息率前 25%（div fillna 0；len>20 才启用，top_k=max(10, 25%)）— 原逻辑同款
    # parity 模式下窗口固定为期末日期（复刻旧 runner load_context_data(end) 口径）
    div_date = context.run_params.get('div_ref_date') or prev_td
    div_map = get_dividend_map(div_date)
    if div_map and len(candidates) > 20:
        scored = [(code, price, mv, div_map.get(code, 0.0) / price)
                  for code, price, mv in candidates]
        top_k = max(10, int(len(scored) * 0.25))
        scored.sort(key=lambda x: x[3], reverse=True)   # 稳定排序，同分保序
        candidates = [(c, p, m) for c, p, m, _ in scored[:top_k]]

    # 最小市值 top N
    candidates.sort(key=lambda x: x[2])
    g.hold_list = [c for c, _p, _m in candidates[:g.stock_num]]


def my_trade(context):
    """开盘调仓：清仓不在候选池的，买入新候选（等权 total_value/g.stock_num）。

    已持仓且仍在候选池的不加减仓（对齐旧 runner 口径：不做再平衡）。
    """
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
    """盘中 14:50：高开(>5%)回落(<3.5%) 减半仓。平价模式下不注册。"""
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
