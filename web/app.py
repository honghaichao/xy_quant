import os
import sys

# 添加项目根目录到sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
import duckdb
import pandas as pd
import numpy as np
import psycopg
from datetime import datetime, timedelta

# Agent API路由
from web.api.agent import agent_bp
from web.api.data_update import data_update_bp
from web.api.backtest import backtest_bp
from utils.stock_name import load_name_map, resolve_name

# Vue 前端 build 产物路径
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')

from config.settings import settings
DB_PATH = os.path.abspath(settings.duckdb_path)


def serve_frontend_index():
    """优先返回 Vue 构建产物；若 dist 不存在则回退到后端模板首页。"""
    dist_index = os.path.join(FRONTEND_DIST, 'index.html')
    if os.path.exists(dist_index):
        return send_from_directory(FRONTEND_DIST, 'index.html')
    return render_template('index.html')

app = Flask(__name__)
CORS(app)

# 注册蓝图
app.register_blueprint(agent_bp)
app.register_blueprint(data_update_bp)
app.register_blueprint(backtest_bp)

DB_PATH = os.path.abspath(settings.duckdb_path)

# 全局股票名称缓存（PG stock_basic 更新频率低，使用公共模块缓存）


def _resolve_name(code: str, name: str) -> str:
    """If name equals code (unresolved), look up PG stock_basic."""
    if name and name != code:
        return name
    return resolve_name(str(code))

# 策略ID到中文名称映射
STRATEGY_NAME_MAP = {
    'b1': 'B1策略',
    'b2': 'B2策略',
    'blk': 'BLK策略',
    'blkB2': 'BLKB2策略',
    'dl': 'DL策略',
    'dz30': 'DZ30策略',
    'scb': 'SCB策略',
}
SELL_STRATEGY_NAME_MAP = {
    's1_full': 'S1满仓信号',
    's1_half': 'S1半仓信号',
    '跌破多空线': '跌破多空线',
    '止损': '止损信号',
}

def get_db():
    return duckdb.connect(DB_PATH, read_only=True)

def get_latest_trading_date():
    db = get_db()
    try:
        latest = db.execute("SELECT MAX(trade_date) FROM daily_bar").fetchone()[0]
        if latest:
            return latest.strftime('%Y-%m-%d')
    finally:
        db.close()
    return datetime.now().strftime('%Y-%m-%d')

def code_to_ts_code(code: str) -> str:
    """转换股票代码为tushare格式"""
    code = str(code)
    if code.startswith('6'):
        return f"{code}.SH"
    else:
        return f"{code}.SZ"

def clean_df_for_json(df):
    for col in df.columns:
        if df[col].dtype == 'object' or str(df[col].dtype).startswith('datetime'):
            df[col] = df[col].apply(lambda x: None if pd.isna(x) else (x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x))
        elif pd.api.types.is_numeric_dtype(df[col]):
            # Replace NaN, Inf, -Inf with None for valid JSON
            df[col] = df[col].replace([np.nan, np.inf, -np.inf], None)
    return df

def map_sell_reason(reason):
    """将卖出原因映射为可读信号名称"""
    if not reason:
        return '信号卖出'

    # CSV 格式支持: "S1_FULL,跌破多空线"
    labels = []
    parts = str(reason).split(',')
    reason_map = {
        'S1_FULL': 'S1 满仓信号',
        'S1_HALF': 'S1 半仓信号',
        '止损': '止损信号',
        '跌破多空线': '跌破多空线信号',
    }
    for part in parts:
        part = part.strip()
        labels.append(reason_map.get(part, part))
    return ','.join(labels) if labels else f'信号卖出({reason})'

@app.route('/')
def index():
    """Vue 前端首页"""
    return serve_frontend_index()

@app.route('/<path:filename>')
def static_files(filename):
    """Vue 静态资源 (JS/CSS/图片等) + SPA 页面路由"""
    # 新模板页面：放行到独立 HTML 路由
    if filename.split('/')[0] in ('factors', 'live', 'risk', 'stock', 'money-flow'):
        return serve_frontend_index()
    # 不是 /api/ 也不在 dist 目录中 → SPA 路由，由 Vue 接管
    if not filename.startswith('api/'):
        file_path = os.path.join(FRONTEND_DIST, filename)
        if os.path.exists(file_path) and not os.path.isdir(file_path):
            return send_from_directory(FRONTEND_DIST, filename)
        return serve_frontend_index()
    # /api/ 请求：只拦截那些没被显式路由注册的
    return jsonify({'error': 'Not found'}), 404

@app.route('/agent')
def agent():
    return serve_frontend_index()

@app.route('/agent/history')
def agent_history():
    return serve_frontend_index()

@app.route('/data-update')
def data_update():
    return serve_frontend_index()

@app.route('/api/positions')
def api_positions():
    db = get_db()
    try:
        # 获取排序参数，默认按buy_date DESC
        sort = request.args.get('sort', 'buy_date')
        order = request.args.get('order', 'desc')

        # 验证排序字段白名单
        allowed_sort_fields = {'buy_date', 'profit_pct', 'profit_loss', 'current_price', 'buy_price', 'name', 'code'}
        if sort not in allowed_sort_fields:
            sort = 'buy_date'

        # 验证排序方向
        order = order.upper() if order.upper() in ('ASC', 'DESC') else 'DESC'

        df = db.execute(f"""
            SELECT 
                id, code, name, strategy,
                buy_date, shares, buy_price,
                buy_change_pct, buy_score_b1, buy_score_b2,
                current_price, profit_loss, profit_pct,
                stop_loss_pct, status, notes,
                ROUND(shares * buy_price * 0.9998, 2) as position_amount
            FROM positions 
            WHERE status = 'holding'
            ORDER BY {sort} {order}
        """).df()
        
        latest_date = get_latest_trading_date()
        if latest_date and not df.empty:
            # 优化：批量查询所有持仓股票的最新价格，避免 N+1 查询
            codes = df['code'].tolist()
            if codes:
                # 转换codes为tushare格式
                ts_codes = [code_to_ts_code(c) for c in codes]
                price_df = db.execute("""
                    SELECT ts_code, close
                    FROM daily_bar
                    WHERE trade_date = ? AND ts_code IN (""" + ','.join(['?' for _ in ts_codes]) + """)
                """, [latest_date] + ts_codes).df()
                
                # 创建价格映射
                price_map = dict(zip(price_df['ts_code'], price_df['close']))
                
                for idx, row in df.iterrows():
                    ts_code = code_to_ts_code(row['code'])
                    current_price = price_map.get(ts_code)
                    if current_price is not None:
                        df.at[idx, 'current_price'] = current_price
                        if row['buy_price']:
                            profit_pct = (current_price - row['buy_price']) / row['buy_price'] * 100
                            profit_loss = (current_price - row['buy_price']) * row['shares']
                            df.at[idx, 'profit_pct'] = round(profit_pct, 2)
                            df.at[idx, 'profit_loss'] = round(profit_loss, 2)
        
        df = clean_df_for_json(df)
        positions = df.to_dict('records')
        
        # 查询历史交易总盈亏
        history_profit = db.execute("SELECT COALESCE(SUM(profit_loss), 0) FROM positions WHERE status = 'sold'").fetchone()[0]
        
        total_capital = 500000  # 总资金
        total_value = sum(p['current_price'] * p['shares'] if p['current_price'] else 0 for p in positions)
        total_cost = sum(p['buy_price'] * p['shares'] if p['buy_price'] else 0 for p in positions)
        holding_profit = total_value - total_cost  # 持仓盈亏
        total_profit = holding_profit + history_profit  # 总盈亏 = 持仓盈亏 + 历史盈亏
        available_cash = total_capital - total_value + total_profit  # 可用资金 = 50万 - 持仓市值 + 总盈亏
        
        return jsonify({
            'positions': positions,
            'summary': {
                'total_value': round(total_value, 2),
                'total_cost': round(total_cost, 2),
                'holding_profit': round(holding_profit, 2),
                'history_profit': round(history_profit, 2),
                'total_profit': round(total_profit, 2),
                'profit_pct': round(total_profit / total_cost * 100, 2) if total_cost > 0 else 0,
                'count': len(positions),
                'available_cash': round(available_cash, 2)
            }
        })
    finally:
        db.close()

@app.route('/api/history')
def api_history():
    db = get_db()
    try:
        df = db.execute("""
            SELECT 
                code, name, strategy,
                buy_date, buy_price, shares,
                sell_date, sell_price, sell_reason,
                profit_loss, profit_pct
            FROM positions 
            WHERE status = 'sold'
            ORDER BY sell_date DESC
        """).df()
        
        df['buy_signal_type'] = df['strategy'].apply(lambda x: x if x else '趋势择时')
        df['sell_signal_type'] = df['sell_reason'].apply(lambda x: map_sell_reason(x) if x else '信号卖出')
        
        df = clean_df_for_json(df)
        history = df.to_dict('records')
        
        total_profit = sum(p['profit_loss'] if p['profit_loss'] else 0 for p in history)
        win_count = len([p for p in history if p['profit_loss'] and p['profit_loss'] > 0])
        loss_count = len([p for p in history if p['profit_loss'] and p['profit_loss'] < 0])
        
        win_total = sum(p['profit_loss'] for p in history if p['profit_loss'] and p['profit_loss'] > 0)
        loss_total = abs(sum(p['profit_loss'] for p in history if p['profit_loss'] and p['profit_loss'] < 0))
        avg_win = win_total / win_count if win_count > 0 else 0
        avg_loss = loss_total / loss_count if loss_count > 0 else 0
        profit_loss_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0
        
        return jsonify({
            'history': history,
            'summary': {
                'total_trades': len(history),
                'total_profit': round(total_profit, 2),
                'win_count': win_count,
                'loss_count': loss_count,
                'win_rate': round(win_count / len(history) * 100, 2) if len(history) > 0 else 0,
                'profit_loss_ratio': profit_loss_ratio
            }
        })
    finally:
        db.close()

@app.route('/api/history/analysis')
def api_history_analysis():
    """综合分析历史交易数据 — 从 positions 表计算真实胜率/收益/月度分布。"""
    db = get_db()
    try:
        sold = db.execute(
            "SELECT code, name, strategy, buy_date, sell_date, buy_price, sell_price,"
            "  shares, profit_loss, profit_pct, sell_reason"
            " FROM positions WHERE status = 'sold' ORDER BY sell_date DESC"
        ).fetchall()
        if not sold:
            return jsonify({"error": "暂无已平仓记录", "total": 0})

        wins = [r for r in sold if r[-4] and r[-4] > 0]
        monthly = {}
        for r in sold:
            m = str(r[4])[:7]  # sell_date → YYYY-MM
            monthly.setdefault(m, {"trades": 0, "wins": 0, "total_pnl": 0.0})
            monthly[m]["trades"] += 1
            if (r[-4] or 0) > 0:
                monthly[m]["wins"] += 1
            monthly[m]["total_pnl"] += float(r[-4] or 0)

        by_strategy = {}
        for r in sold:
            s = r[2] or "未知"
            by_strategy.setdefault(s, {"trades": 0, "wins": 0, "total_pnl": 0.0})
            by_strategy[s]["trades"] += 1
            if (r[-4] or 0) > 0:
                by_strategy[s]["wins"] += 1
            by_strategy[s]["total_pnl"] += float(r[-4] or 0)

        total_pnl = sum(float(r[-4] or 0) for r in sold)
        win_count = len(wins)
        return jsonify({
            "total_trades": len(sold),
            "win_count": win_count,
            "win_rate": round(win_count / len(sold) * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(sum(float(r[-4] or 0) for r in wins) / max(win_count, 1), 2),
            "avg_loss": round(sum(float(r[-4] or 0) for r in sold if (r[-4] or 0) <= 0) / max(len(sold) - win_count, 1), 2),
            "monthly": [{"month": m, **v} for m, v in sorted(monthly.items())],
            "by_strategy": {k: {"trades": v["trades"], "win_rate": round(v["wins"] / max(v["trades"], 1) * 100, 2),
                                "total_pnl": round(v["total_pnl"], 2)} for k, v in by_strategy.items()},
        })
    finally:
        db.close()


@app.route('/api/signals')
def api_signals():
    db = get_db()
    try:
        latest_date = db.execute("SELECT MAX(date) FROM daily_signals").fetchone()[0]
        
        if not latest_date:
            return jsonify({'signals': [], 'date': None})
        
        date_str = latest_date.strftime('%Y-%m-%d') if hasattr(latest_date, 'strftime') else str(latest_date)
        
        df = db.execute("SELECT * FROM daily_signals WHERE date = ?", [latest_date]).df()
        
        if df.empty:
            return jsonify({'signals': [], 'date': date_str, 'buy_count': 0, 'sell_count': 0})
        
        buy_signal_cols = [c for c in df.columns if c.startswith('signal_buy_')]
        sell_signal_cols = [c for c in df.columns if c in ('signal_s1_full', 'signal_s1_half', 'signal_跌破多空线', 'signal_止损')]
        
        result = []
        buy_count = 0
        sell_count = 0
        
        for _, row in df.iterrows():
            buy_signals = []
            sell_signals = []
            
            for col in buy_signal_cols:
                if row[col] is True or row[col] == 1:
                    strategy_id = col.replace('signal_buy_', '')
                    strategy_name = STRATEGY_NAME_MAP.get(strategy_id, strategy_id)
                    score_col = f'score_{strategy_id}'
                    score = row.get(score_col, 0) or 0
                    buy_signals.append({'strategy': strategy_name, 'score': round(score, 2)})
            
            for col in sell_signal_cols:
                if row[col] is True or row[col] == 1:
                    sell_key = col.replace('signal_', '')
                    strategy_name = SELL_STRATEGY_NAME_MAP.get(sell_key, sell_key)
                    sell_signals.append({'strategy': strategy_name, 'score': round(row.get(f'score_{sell_key}', 0) or 0, 2)})
            
            if buy_signals or sell_signals:
                if buy_signals:
                    buy_count += 1
                if sell_signals:
                    sell_count += 1
                result.append({
                    'code': row['code'],
                    'name': _resolve_name(row['code'], row['name']),
                    'close': round(row['close'], 2) if pd.notna(row['close']) else None,
                    'change_pct': round(row['change_pct'], 2) if pd.notna(row['change_pct']) else None,
                    'open': round(row['open'], 2) if pd.notna(row['open']) else None,
                    'high': round(row['high'], 2) if pd.notna(row['high']) else None,
                    'low': round(row['low'], 2) if pd.notna(row['low']) else None,
                    'volume': int(row['volume']) if pd.notna(row['volume']) else None,
                    'buy_signals': buy_signals,
                    'sell_signals': sell_signals,
                })
        
        result.sort(key=lambda x: max([s['score'] for s in x['buy_signals']] or [0], default=0), reverse=True)
        
        return jsonify({
            'signals': result,
            'date': date_str,
            'buy_count': buy_count,
            'sell_count': sell_count
        })
    finally:
        db.close()

@app.route('/api/equity-curve')
def api_equity_curve():
    import signal
        
    def timeout_handler(signum, frame):
        raise TimeoutError("akshare API timeout")
    
    db = get_db()
    try:
        # 优先从 portfolio_daily + jq_live_nav 合并净值序列
        portfolio = db.execute("""
            SELECT date, total_value, init_cash, position_ratio,
                   closed_pnl, available_cash, total_pnl - COALESCE(closed_pnl,0) AS position_pnl
            FROM portfolio_daily ORDER BY date
        """).fetchall()
        # 合并 JQ 实盘净值
        jq_nav = db.execute("""
            SELECT date, total, initial_cash, positions, 0, cash, 0
            FROM jq_live_nav ORDER BY date
        """).fetchall() or []
        if jq_nav:
            existing = {r[0] for r in portfolio}
            for row in jq_nav:
                if row[0] not in existing:
                    portfolio.append(row)
            portfolio.sort(key=lambda r: r[0])

        if not portfolio:
            dates = []
            for i in range(30):
                d = datetime.now() - timedelta(days=29-i)
                dates.append(d.strftime('%Y-%m-%d'))
            mock_values = [500000] * 30
            return jsonify({
                'dates': dates,
                'values': mock_values,
                'benchmark': [500000] * 30,
                'total_return': 0,
                'annotations': {
                    'peak': {'date': dates[0], 'value': 500000, 'return_pct': 0},
                    'trough': {'date': dates[-1], 'value': 500000},
                    'max_drawdown': {'date': None, 'pct': 0}
                }
            })
        
        dates = []
        values = []
        position_ratio_list = []
        closed_pnl_list = []
        available_cash_list = []
        position_pnl_list = []
        initial_value = 500000
        
        for p in portfolio:
            date, total_value, init_cash, position_ratio, closed_pnl, available_cash, position_pnl = p
            d_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)
            dates.append(d_str)
            values.append(float(total_value) if total_value else 500000)
            position_ratio_list.append(round(float(position_ratio), 2) if position_ratio else 0)
            closed_pnl_list.append(round(float(closed_pnl), 2) if closed_pnl else 0)
            available_cash_list.append(round(float(available_cash), 2) if available_cash else 0)
            position_pnl_list.append(round(float(position_pnl), 2) if position_pnl else 0)
        
        # initial_value 从第一行的 init_cash 读取
        if portfolio and portfolio[0][2]:
            initial_value = float(portfolio[0][2])
        
        benchmark_values = []
        try:
            # 直接从数据库读取上证指数数据，无需外部API
            index_data = db.execute("""
                SELECT trade_date, close FROM index_daily
                WHERE ts_code = '000001.SH' 
                AND trade_date >= ? AND trade_date <= ?
                ORDER BY trade_date
            """, [dates[0], dates[-1]]).fetchall()
            
            if index_data:
                index_map = {str(row[0]): float(row[1]) for row in index_data}
                first_close = index_map.get(dates[0])
                
                if first_close and first_close > 0:
                    for d in dates:
                        close = index_map.get(d)
                        if close:
                            benchmark_values.append(initial_value * close / first_close)
                        else:
                            benchmark_values.append(benchmark_values[-1] if benchmark_values else initial_value)
                else:
                    benchmark_values = [initial_value] * len(dates)
            else:
                benchmark_values = [initial_value] * len(dates)
        except Exception as e:
            print(f"获取上证指数失败: {e}")
            benchmark_values = [initial_value] * len(dates)
        
        current_value = values[-1] if values else initial_value
        total_return = (current_value - initial_value) / initial_value * 100 if initial_value > 0 else 0
        
        # ========== 计算关键指标 ==========
        initial_value_const = 500000

        # 最大收益率和日期 (峰值)
        peak_value = max(values)
        peak_idx = values.index(peak_value)
        peak_date = dates[peak_idx]
        peak_return = (peak_value - initial_value_const) / initial_value_const * 100

        # 最低市值和日期 (谷值)
        trough_value = min(values)
        trough_idx = values.index(trough_value)
        trough_date = dates[trough_idx]

        # 最大回撤计算
        max_drawdown = 0
        max_drawdown_date = None
        peak_so_far = initial_value_const

        for i, (d, v) in enumerate(zip(dates, values)):
            if v > peak_so_far:
                peak_so_far = v
            drawdown = (peak_so_far - v) / peak_so_far * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_date = d

        return jsonify({
            'dates': dates,
            'values': [round(v, 2) for v in values],
            'benchmark': [round(v, 2) for v in benchmark_values],
            'total_return': round(total_return, 2),
            'annotations': {
                'peak': {
                    'date': peak_date,
                    'value': round(peak_value, 2),
                    'return_pct': round(peak_return, 2)
                },
                'trough': {
                    'date': trough_date,
                    'value': round(trough_value, 2)
                },
                'max_drawdown': {
                    'date': max_drawdown_date,
                    'pct': round(max_drawdown, 2)
                }
            },
            'position_ratio': position_ratio_list,
            'closed_pnl': closed_pnl_list,
            'available_cash': available_cash_list,
            'position_pnl': position_pnl_list
        })
    finally:
        db.close()

@app.route('/api/strategy-comparison')
def api_strategy_comparison():
    """
    获取策略对比数据

    从 portfolio_daily_strategy 表获取各策略的真实每日表现数据。
    """
    db = get_db()
    try:
        INITIAL_CAPITAL = 500000.0

        strategies = db.execute("""
            SELECT DISTINCT strategy
            FROM portfolio_daily_strategy
            WHERE strategy IS NOT NULL
            ORDER BY strategy
        """).fetchall()

        if not strategies:
            return jsonify({
                'strategies': [],
                'dates': [],
                'curves': {},
                'metrics': {}
            })

        colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']

        strategy_data = {}

        for i, (strategy_name,) in enumerate(strategies):
            daily_data = db.execute("""
                SELECT date, total_pnl, closed_pnl, position_pnl, trade_count
                FROM portfolio_daily_strategy
                WHERE strategy = ?
                ORDER BY date
            """, [strategy_name]).fetchall()

            if not daily_data:
                continue

            dates = []
            values = []
            cumulative_pnl = 0.0

            for row in daily_data:
                date, total_pnl, closed_pnl, position_pnl, trade_count = row
                date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)
                dates.append(date_str)

                if total_pnl is not None:
                    cumulative_pnl = float(total_pnl)

                portfolio_value = INITIAL_CAPITAL + cumulative_pnl
                values.append(round(portfolio_value, 2))

            if not dates:
                continue

            strategy_data[strategy_name] = {
                'dates': dates,
                'values': values,
                'trade_count': sum(row[4] for row in daily_data if row[4] is not None),
                'color': colors[i % len(colors)]
            }

        all_dates = set()
        for sd in strategy_data.values():
            all_dates.update(sd['dates'])

        sorted_dates = sorted(all_dates)
        date_to_idx = {d: i for i, d in enumerate(sorted_dates)}

        curves = {}
        metrics = {}

        for strategy_name, sd in strategy_data.items():
            aligned_values = []
            last_value = INITIAL_CAPITAL
            date_to_value = dict(zip(sd['dates'], sd['values']))

            for date_str in sorted_dates:
                if date_str in date_to_value:
                    v = date_to_value[date_str]
                    if v is not None:
                        last_value = v
                aligned_values.append(last_value)

            values = aligned_values

            valid_values = [v for v in values if v is not None]
            if not valid_values:
                continue

            final_value = valid_values[-1]
            total_return = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL

            peak = INITIAL_CAPITAL
            max_drawdown = 0
            for v in valid_values:
                if v > peak:
                    peak = v
                drawdown = (peak - v) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

            if len(valid_values) > 1:
                returns = [(valid_values[j] - valid_values[j-1]) / valid_values[j-1] for j in range(1, len(valid_values)) if valid_values[j-1] != 0]
                if returns:
                    avg_ret = sum(returns) / len(returns)
                    variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
                    std_dev = variance ** 0.5
                    sharpe_ratio = avg_ret / std_dev * (252 ** 0.5) if std_dev > 0 else 0
                else:
                    sharpe_ratio = 0
            else:
                sharpe_ratio = 0

            curves[strategy_name] = {
                'data': values,
                'initial_value': INITIAL_CAPITAL,
                'color': sd['color']
            }

            metrics[strategy_name] = {
                'total_return': round(total_return, 4),
                'annualized_return': round(total_return * 252 / len(valid_values), 4) if valid_values else 0,
                'sharpe_ratio': round(sharpe_ratio, 2),
                'max_drawdown': round(max_drawdown, 4),
                'win_rate': 0,
                'total_trades': int(sd['trade_count'])
            }

        return jsonify({
            'strategies': [s[0] for s in strategies if s[0] in curves],
            'dates': sorted_dates,
            'initial_value': INITIAL_CAPITAL,
            'curves': curves,
            'metrics': metrics
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/stats')
def api_stats():
    db = get_db()
    try:
        holding_count = db.execute("SELECT COUNT(*) FROM positions WHERE status = 'holding'").fetchone()[0]
        sold_count = db.execute("SELECT COUNT(*) FROM positions WHERE status = 'sold'").fetchone()[0]
        
        latest_date = db.execute("SELECT MAX(date) FROM daily_signals").fetchone()[0]
        buy_signals_count = 0
        if latest_date:
            buy_signals_count = db.execute("""
                SELECT COUNT(*) FROM daily_signals 
                WHERE date = ? AND (signal_buy_b1 = true OR signal_buy_b2 = true)
            """, [latest_date]).fetchone()[0]
        
        return jsonify({
            'holding_count': holding_count,
            'sold_count': sold_count,
            'today_buy_signals': buy_signals_count,
            'latest_date': latest_date.strftime('%Y-%m-%d') if latest_date else None
        })
    finally:
        db.close()

@app.route('/api/multi-signal-resonance')
def api_multi_signal_resonance():
    """获取多信号共振股票"""
    date_str = request.args.get('date')
    if not date_str:
        # 默认前一天
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    db = get_db()
    try:
        result = db.execute("""
            SELECT code, name,
                   signal_buy_b1, signal_buy_b2, signal_buy_blk, signal_buy_dl,
                   signal_buy_dz30, signal_buy_scb, signal_buy_blkB2,
                   close, change_pct
            FROM daily_signals
            WHERE date = ?
            AND (CAST(signal_buy_b1 AS INT) + CAST(signal_buy_b2 AS INT) + 
                 CAST(signal_buy_blk AS INT) + CAST(signal_buy_dl AS INT) + 
                 CAST(signal_buy_dz30 AS INT) + CAST(signal_buy_scb AS INT) + 
                 CAST(signal_buy_blkB2 AS INT)) >= 2
            ORDER BY (CAST(signal_buy_b1 AS INT) + CAST(signal_buy_b2 AS INT) + 
                      CAST(signal_buy_blk AS INT) + CAST(signal_buy_dl AS INT) + 
                      CAST(signal_buy_dz30 AS INT) + CAST(signal_buy_scb AS INT) + 
                      CAST(signal_buy_blkB2 AS INT)) DESC,
                     close DESC
        """, [date_str]).fetchall()
        
        signal_names = ['B1', 'B2', 'BLK', 'DL', 'DZ30', 'SCB', 'BLKB2']
        data = []
        for row in result:
            signals = [signal_names[i] for i, v in enumerate(row[2:9]) if v]
            data.append({
                'code': row[0],
                'name': _resolve_name(row[0], row[1]),
                'signal_count': len(signals),
                'signals': signals,
                'close': float(row[9]) if row[9] else 0,
                'change_pct': float(row[10]) if row[10] else 0
            })
        
        return jsonify({
            'date': date_str,
            'stocks': data,
            'count': len(data)
        })
    finally:
        db.close()

@app.route('/api/multi-signal-trend')
def api_multi_signal_trend():
    """获取多信号共振趋势数据"""
    db = get_db()
    try:
        result = db.execute("""
            SELECT date,
                   SUM(CAST(signal_buy_b1 AS INT)) as b1_count,
                   SUM(CAST(signal_buy_b2 AS INT)) as b2_count,
                   SUM(CAST(signal_buy_blk AS INT)) as blk_count,
                   SUM(CAST(signal_buy_dl AS INT)) as dl_count,
                   SUM(CAST(signal_buy_dz30 AS INT)) as dz30_count,
                   SUM(CAST(signal_buy_scb AS INT)) as scb_count,
                   SUM(CAST(signal_buy_blkB2 AS INT)) as blkB2_count,
                   COUNT(*) as total_count
            FROM daily_signals
            WHERE (CAST(signal_buy_b1 AS INT) + CAST(signal_buy_b2 AS INT) + 
                   CAST(signal_buy_blk AS INT) + CAST(signal_buy_dl AS INT) + 
                   CAST(signal_buy_dz30 AS INT) + CAST(signal_buy_scb AS INT) + 
                   CAST(signal_buy_blkB2 AS INT)) >= 2
            GROUP BY date
            ORDER BY date
        """).fetchall()
        
        dates = []
        total_counts = []
        signal_data = {
            'B1': [], 'B2': [], 'BLK': [], 'DL': [], 'DZ30': [], 'SCB': [], 'BLKB2': []
        }
        
        for row in result:
            date_str = row[0].strftime('%Y-%m-%d') if hasattr(row[0], 'strftime') else str(row[0])
            dates.append(date_str)
            total_counts.append(int(row[8]))
            signal_data['B1'].append(int(row[1]))
            signal_data['B2'].append(int(row[2]))
            signal_data['BLK'].append(int(row[3]))
            signal_data['DL'].append(int(row[4]))
            signal_data['DZ30'].append(int(row[5]))
            signal_data['SCB'].append(int(row[6]))
            signal_data['BLKB2'].append(int(row[7]))
        
        return jsonify({
            'dates': dates,
            'total_counts': total_counts,
            'signal_data': signal_data
        })
    finally:
        db.close()


@app.route('/multi-signal-resonance')
def multi_signal_resonance():
    return serve_frontend_index()


@app.route('/api/multi-signal-resonance/dates')
def api_multi_signal_resonance_dates():
    """API: 获取多策略共振可用的日期列表"""
    db = get_db()
    try:
        dates = db.execute("SELECT DISTINCT date FROM daily_signals ORDER BY date DESC").fetchall()
        return jsonify({
            'dates': [{'value': d[0].strftime('%Y-%m-%d'), 'label': d[0].strftime('%Y-%m-%d')} for d in dates]
        })
    finally:
        db.close()


@app.route('/api/stock/<code>/kline')
def api_stock_kline(code):
    """API: 个股K线数据 — 日线 OHLCV + 分钟线

    参数:
        type=daily  日线 (默认)
        type=minute 分钟线 (最近5天)
        limit=200   返回条数上限
    """
    db = get_db()
    try:
        ts_code = code_to_ts_code(code)
        chart_type = request.args.get('type', 'daily')
        limit = min(int(request.args.get('limit', 200)), 500)

        if chart_type == 'minute':
            # 最近5个交易日的分钟线
            df = db.execute("""
                SELECT datetime, open, high, low, close, vol
                FROM minute_bar
                WHERE ts_code = ?
                ORDER BY datetime DESC
                LIMIT ?
            """, [ts_code, min(limit * 240, 4800)]).df()  # ~240 bars/day
        else:
            # 日线
            df = db.execute("""
                SELECT trade_date, open, high, low, close, vol
                FROM daily_bar
                WHERE ts_code = ?
                ORDER BY trade_date ASC
            """, [ts_code]).df()
            # Return last N days
            if len(df) > limit:
                df = df.tail(limit)

        if df.empty:
            return jsonify({'code': code, 'name': _resolve_name(code, code), 'data': []})

        # Add MA5, MA10, MA20 (before clean to catch NaN)
        df['ma5'] = df['close'].rolling(window=5).mean().round(2)
        df['ma10'] = df['close'].rolling(window=10).mean().round(2)
        df['ma20'] = df['close'].rolling(window=20).mean().round(2)
        df['ma60'] = df['close'].rolling(window=60).mean().round(2)
        df['ma120'] = df['close'].rolling(window=120).mean().round(2)

        # ── Support / Resistance ──
        # Pivot: recent 20-day high (resistance) and low (support)
        if len(df) >= 20:
            df['resistance'] = df['high'].rolling(window=20).max().round(2)
            df['support'] = df['low'].rolling(window=20).min().round(2)
            # Bollinger Bands
            ma20 = df['ma20']
            std20 = df['close'].rolling(window=20).std()
            df['boll_upper'] = (ma20 + 1.5 * std20).round(2)
            df['boll_lower'] = (ma20 - 1.5 * std20).round(2)

        # ── Buy / Sell signal markers (from daily_signals) with rich info ──
        signal_rows = db.execute(
            """SELECT date,
                      signal_buy_b1, signal_buy_b2, signal_buy_blk, signal_buy_blkB2,
                      signal_buy_scb, signal_buy_dz30,
                      signal_s1_full, signal_s1_half, signal_跌破多空线,
                      score_b1, score_b2, score_blk, score_blkB2, score_scb, score_dz30, score_s1,
                      change_pct, volume, close
               FROM daily_signals WHERE code=? AND date >= ?
               ORDER BY date""",
            [code, df['trade_date'].iloc[0].isoformat() if hasattr(df['trade_date'].iloc[0], 'isoformat')
             else str(df['trade_date'].iloc[0])[:10]],
        ).fetchall()

        buy_markers = {}   # date → {label, score, change_pct, volume}
        sell_markers = {}  # date → {label, score_s1}
        strategy_labels = {'b1':'B1','b2':'B2','blk':'BLK','blkB2':'BLKB2','scb':'SCB','dz30':'DZ30'}
        for row in signal_rows:
            d = row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0])[:10]
            # Column indices: 0=date, 1-6=buy booleans, 7-9=sell booleans, 10-16=scores, 17=change_pct, 18=volume, 19=close
            chg_pct = round(float(row[17] or 0), 2) if row[17] is not None else 0
            vol = int(row[18] or 0) if row[18] is not None else 0
            close_price = round(float(row[19] or 0), 2) if row[19] is not None else 0

            # buy signals
            strategies = []
            best_score = 0
            for i, col in enumerate(['signal_buy_b1','signal_buy_b2','signal_buy_blk',
                                      'signal_buy_blkB2','signal_buy_scb','signal_buy_dz30'], start=1):
                if row[i]:
                    abbr = col.replace('signal_buy_','').upper()
                    score_val = float(row[9 + i] or 0) if row[9 + i] is not None else 0
                    strategies.append(abbr)
                    if score_val > best_score:
                        best_score = score_val
            if strategies:
                buy_markers[d] = {
                    'label': ','.join(s[:3] for s in strategies),
                    'strategies': strategies,
                    'best_score': round(best_score, 1),
                    'change_pct': chg_pct,
                    'volume': vol,
                    'close': close_price,
                }

            # sell signals
            sell_reasons = []
            sell_score = float(row[16] or 0) if row[16] is not None else 0  # score_s1
            if row[7]: sell_reasons.append('S1_FULL')
            if row[8]: sell_reasons.append('S1_HALF')
            if row[9]: sell_reasons.append('BROKEN_MA')
            if sell_reasons:
                sell_markers[d] = {
                    'label': ','.join(sell_reasons),
                    'reasons': sell_reasons,
                    'score_s1': round(sell_score, 1),
                    'change_pct': chg_pct,
                    'close': close_price,
                }

        # ── Enrich each bar with metadata ──
        # Compute turnover % for each bar (vol / vol_ma20)
        vol_ma20 = df['vol'].rolling(window=20).mean().round(0)
        for i in range(len(df)):
            if vol_ma20.iloc[i] > 0 and df['vol'].iloc[i] > 0:
                df.at[df.index[i], 'turnover'] = round(df['vol'].iloc[i] / vol_ma20.iloc[i], 2)
            else:
                df.at[df.index[i], 'turnover'] = None

        # Ensure turnover is numeric before clean
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce')

        df = clean_df_for_json(df)

        # Match markers to bar data and attach enriched info
        data = df.to_dict('records')
        for bar in data:
            d = str(bar.get('trade_date','') or '')
            if d in buy_markers:
                bm = buy_markers[d]
                bm['price'] = round(bar['low'] * 0.98, 2) if bar.get('low') else None
                bar['buy_signal'] = bm['label']
                bar['buy_info'] = {
                    'strategies': bm['strategies'],
                    'best_score': bm['best_score'],
                    'change_pct': bm['change_pct'],
                    'volume': bm['volume'],
                    'close': bm['close'],
                    'marker_price': bm['price'],
                }
            if d in sell_markers:
                sm = sell_markers[d]
                sm['price'] = round(bar['high'] * 1.02, 2) if bar.get('high') else None
                bar['sell_signal'] = sm['label']
                bar['sell_info'] = {
                    'reasons': sm['reasons'],
                    'score_s1': sm['score_s1'],
                    'change_pct': sm['change_pct'],
                    'close': sm['close'],
                    'marker_price': sm['price'],
                }
            # Add turnover ratio to bar
            if bar.get('turnover') is not None:
                bar['turnover'] = round(bar['turnover'], 2)

        name = _resolve_name(code, code)

        return jsonify({
            'code': code,
            'name': name,
            'type': chart_type,
            'count': len(data),
            'data': data,
        })
    finally:
        db.close()


@app.route('/api/stock/<code>/info')
def api_stock_info(code):
    """API: 个股基本信息 + 最新信号"""
    db = get_db()
    try:
        name = _resolve_name(code, code)
        ts_code = code_to_ts_code(code)

        # 最新日线
        latest = db.execute(
            "SELECT trade_date, open, high, low, close, vol FROM daily_bar WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
            [ts_code]
        ).fetchone()

        # 最新信号
        signals = db.execute(
            "SELECT date, signal_buy_b1, signal_buy_b2, signal_buy_blk, signal_buy_blkB2, "
            "signal_buy_scb, signal_buy_dz30, signal_s1_full, signal_s1_half, signal_跌破多空线 "
            "FROM daily_signals WHERE code=? ORDER BY date DESC LIMIT 5",
            [code]
        ).fetchall()

        signal_list = []
        for row in signals:
            date_str = row[0].strftime('%Y-%m-%d') if hasattr(row[0], 'strftime') else str(row[0])
            buy_signals = []
            if row[1]: buy_signals.append('B1')
            if row[2]: buy_signals.append('B2')
            if row[3]: buy_signals.append('BLK')
            if row[4]: buy_signals.append('BLKB2')
            if row[5]: buy_signals.append('SCB')
            if row[6]: buy_signals.append('DZ30')
            sell_signals = []
            if row[7]: sell_signals.append('S1_FULL')
            if row[8]: sell_signals.append('S1_HALF')
            if row[9]: sell_signals.append('BROKEN_MA')
            if buy_signals or sell_signals:
                signal_list.append({
                    'date': date_str,
                    'buy_signals': buy_signals,
                    'sell_signals': sell_signals,
                })

        return jsonify({
            'code': code,
            'name': name,
            'latest': {
                'date': latest[0].strftime('%Y-%m-%d') if latest and hasattr(latest[0], 'strftime') else str(latest[0]) if latest else None,
                'open': latest[1] if latest else None,
                'high': latest[2] if latest else None,
                'low': latest[3] if latest else None,
                'close': latest[4] if latest else None,
                'vol': latest[5] if latest else None,
            } if latest else None,
            'recent_signals': signal_list,
        })
    finally:
        db.close()


@app.route('/api/stock/search')
def api_stock_search():
    """API: 股票搜索 — 按代码或名称模糊匹配"""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return jsonify({'results': []})

    name_map = load_name_map()
    results = []
    for code, name in name_map.items():
        if q.lower() in code.lower() or q in name:
            results.append({'code': code, 'name': name})
        if len(results) >= 20:
            break

    return jsonify({'results': results})


@app.route('/stock/<code>')
def stock_detail_page(code):
    """个股详情页 — 独立 K 线图模板"""
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    template_path = os.path.join(template_dir, 'stock.html')
    if os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    return serve_frontend_index()


@app.route('/backtest/<run_id>')
def backtest_detail_page(run_id):
    """回测详情页 — 菜场大妈等策略的完整回测报告"""
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    template_path = os.path.join(template_dir, 'backtest_detail.html')
    if os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
        return html.replace('{{ run_id }}', run_id)
    return render_template('backtest_detail.html', run_id=run_id)


@app.route('/backtest')
def backtest_list_page():
    """回测列表页"""
    return serve_frontend_index()

# ═══════════════════════════════════════════════════════════════
# 独立数据分析页面（Vue SPA 源码缺失，用 Flask 模板 + ECharts 补齐）
# ═══════════════════════════════════════════════════════════════

@app.route('/factors')
def factors_page():
    """因子分析仪表盘"""
    return render_template('factors.html')


@app.route('/api/factors/rank')
def api_factors_rank():
    """因子 IC 排名（全量，按 |IC| 降序）。"""
    db = get_db()
    try:
        rows = db.execute("""
            SELECT factor_name, abs_ic_mean, ic_std, n_days, rank
            FROM factor_rank ORDER BY abs_ic_mean DESC
        """).fetchall()
        # 补方向
        fnames = [r[0] for r in rows]
        if fnames:
            placeholders = ",".join([f"'{f}'" for f in fnames])
            dir_rows = db.execute(f"""
                SELECT factor_name, AVG(ic) FROM factor_ic
                WHERE factor_name IN ({placeholders})
                GROUP BY factor_name
            """).fetchall()
            direction = {r[0]: (1 if (r[1] or 0) > 0 else -1) for r in dir_rows}
        else:
            direction = {}
        rank_list = []
        for r in rows:
            fn = r[0]
            avg_ic = float(r[1] or 0)
            std = float(r[2] or 0)
            rank_list.append({
                "factor_name": fn,
                "abs_ic_mean": round(avg_ic, 4),
                "ic_std": round(std, 4),
                "ic_ir": round(avg_ic / std, 3) if std > 0 else 0,
                "n_days": r[3] or 0,
                "direction": direction.get(fn, 0),
            })
        return jsonify({"factors": rank_list, "total": len(rank_list)})
    finally:
        db.close()


@app.route('/api/factors/<name>/ic')
def api_factors_ic(name: str):
    """单个因子的每日 IC 时间序列。"""
    db = get_db()
    try:
        rows = db.execute("""
            SELECT date, ic, sample_count FROM factor_ic
            WHERE factor_name = ? ORDER BY date
        """, [name]).fetchall()
        dates = [str(r[0]) for r in rows]
        ic = [float(r[1] or 0) for r in rows]
        cum = [sum(ic[:i+1]) for i in range(len(ic))] if ic else []
        return jsonify({
            "factor_name": name,
            "dates": dates,
            "ic": ic,
            "cumulative_ic": cum,
            "n": len(dates),
        })
    finally:
        db.close()


@app.route('/api/factors/snapshot')
def api_factors_snapshot():
    """因子今日选股 top 30 + signal_events 交叉标记。"""
    try:
        from engine.factor_scorer import score_snapshot
        r = score_snapshot(target_date=None, top_n=30)
        db = get_db()
        try:
            # 交叉标记 signal_events 买入信号
            codes_str = ",".join([f"'{c}'" for c in r.top_codes])
            events = db.execute(f"""
                SELECT code, signal_abbrev, MAX(score) FROM signal_events
                WHERE signal_type='buy' AND code IN ({codes_str})
                GROUP BY 1,2
            """).fetchall()
            ev_map = {}
            for ev in events:
                ev_map.setdefault(ev[0], []).append(ev[1])
        finally:
            db.close()

        top = []
        for code in r.top_codes:
            score = float(r.scores.loc[code, "score"]) if code in r.scores.index else 0
            top.append({
                "code": code,
                "score": round(score, 4),
                "signal_types": ev_map.get(code, []),
            })
        return jsonify({
            "date": str(r.date),
            "factors_used": r.factors_used,
            "top_stocks": top,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/money-flow')
def money_flow_page():
    """全市场资金流页面"""
    return render_template('money_flow.html')


@app.route('/api/money-flow')
def api_money_flow():
    """近 30 天全市场资金流（PG stock_money_flow 聚合）。"""
    try:
        pg = psycopg.connect(settings.pg_dsn)
        try:
            rows = pg.execute("""
                SELECT trade_date,
                       SUM(main_inflow)::BIGINT AS main_net,
                       SUM(big_inflow)::BIGINT   AS big_net,
                       SUM(super_inflow)::BIGINT  AS super_net,
                       COUNT(*) AS n
                FROM stock_money_flow
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 30
            """).fetchall()
        finally:
            pg.close()
        dates = [str(r[0]) for r in reversed(rows)]
        main_net  = [int(r[1] or 0) for r in reversed(rows)]
        big_net   = [int(r[2] or 0) for r in reversed(rows)]
        super_net = [int(r[3] or 0) for r in reversed(rows)]
        counts    = [int(r[4] or 0) for r in reversed(rows)]
        cum = [sum(main_net[:i+1]) for i in range(len(main_net))]
        return jsonify({
            "dates": dates,
            "main_net": main_net,
            "big_net": big_net,
            "super_net": super_net,
            "cumulative_net": cum,
            "counts": counts,
            "days": len(dates),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/money-flow/sector')
def api_money_flow_sector():
    """最新交易日行业板块资金流排名（PG industry_money_flow）。"""
    try:
        pg = psycopg.connect(settings.pg_dsn)
        try:
            latest_date = pg.execute(
                "SELECT MAX(trade_date) FROM industry_money_flow"
            ).fetchone()[0]
            rows = pg.execute("""
                SELECT industry_name, main_inflow,
                       super_inflow, big_inflow, mid_inflow, small_inflow,
                       pct_chg
                FROM industry_money_flow
                WHERE trade_date = %s
                ORDER BY main_inflow DESC
            """, [latest_date]).fetchall()
        finally:
            pg.close()

        sectors = []
        for r in rows:
            name, main, sup, big, mid, small, pct_chg = r
            sectors.append({
                "name": name,
                "main_inflow": round((main or 0), 1),           # 万元
                "super_inflow": round((sup or 0), 1),
                "big_inflow": round((big or 0), 1),
                "mid_inflow": round((mid or 0), 1),
                "small_inflow": round((small or 0), 1),
                "pct_chg": round(pct_chg or 0, 2),
            })

        return jsonify({
            "date": str(latest_date),
            "sectors": sectors,
            "total": len(sectors),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/money-flow/sector/trend')
def api_money_flow_sector_trend():
    """近 30 天 top N 行业资金流时序（用于折线图）。"""
    top_n = request.args.get('top', 10, type=int)
    try:
        pg = psycopg.connect(settings.pg_dsn)
        try:
            # 最近30个交易日
            trade_dates = pg.execute(
                "SELECT DISTINCT trade_date FROM industry_money_flow ORDER BY trade_date DESC LIMIT 30"
            ).fetchall()
            if not trade_dates:
                return jsonify({"error": "no data"}), 500
            date_list = [str(d[0]) for d in reversed(trade_dates)]
            earliest, latest = date_list[0], date_list[-1]

            # 30日净流入总和 top N 行业
            top_industries = pg.execute("""
                SELECT industry_name, SUM(main_inflow) as total
                FROM industry_money_flow
                WHERE trade_date >= %s AND trade_date <= %s
                GROUP BY industry_name
                ORDER BY total DESC
                LIMIT %s
            """, [earliest, latest, top_n]).fetchall()
            industry_names = [r[0] for r in top_industries]

            # 每个行业的每日时序
            ph = ','.join(['%s' for _ in industry_names])
            rows = pg.execute(f"""
                SELECT trade_date, industry_name, main_inflow
                FROM industry_money_flow
                WHERE trade_date >= %s AND trade_date <= %s
                  AND industry_name IN ({ph})
                ORDER BY industry_name, trade_date
            """, [earliest, latest] + industry_names).fetchall()
        finally:
            pg.close()

        # 构建 series
        from collections import defaultdict
        by_industry = defaultdict(lambda: defaultdict(float))
        for r in rows:
            by_industry[r[1]][str(r[0])] = float(r[2] or 0)

        colors = ['#f87171','#38bdf8','#34d399','#fb923c','#a78bfa',
                  '#facc15','#f472b6','#2dd4bf','#eab308','#818cf8']

        series = []
        for idx, name in enumerate(industry_names):
            data = [round(by_industry[name].get(d, 0), 1) for d in date_list]
            series.append({
                "name": name,
                "data": data,
                "color": colors[idx % len(colors)],
            })

        return jsonify({
            "dates": date_list,
            "series": series,
            "unit": "万元（后端存储，前端展示为亿）",
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/money-flow/concept/trend')
def api_money_flow_concept_trend():
    """近 30 天 top N 概念板块资金流时序（从 stock_money_flow + concept_member 聚合）。"""
    top_n = request.args.get('top', 10, type=int)
    try:
        pg = psycopg.connect(settings.pg_dsn)
        try:
            trade_dates = pg.execute(
                "SELECT DISTINCT trade_date FROM stock_money_flow ORDER BY trade_date DESC LIMIT 30"
            ).fetchall()
            if not trade_dates:
                return jsonify({"error": "no data"}), 500
            date_list = [str(d[0]) for d in reversed(trade_dates)]
            earliest, latest = date_list[0], date_list[-1]

            # Aggregate concept-level money flow from stock-level data via concept_member
            top_concepts = pg.execute("""
                SELECT cl.name AS concept_name, SUM(sm.main_inflow) AS total
                FROM concept_member cm
                JOIN stock_money_flow sm ON cm.ts_code = sm.ts_code
                    AND sm.trade_date >= %s AND sm.trade_date <= %s
                JOIN concept_list cl ON cm.concept_code = cl.code
                GROUP BY cl.name
                HAVING COUNT(*) >= 5
                ORDER BY total DESC
                LIMIT %s
            """, [earliest, latest, top_n]).fetchall()
            concept_names = [r[0] for r in top_concepts]

            # Fetch time series for each top concept
            ph = ','.join(['%s' for _ in concept_names])
            rows = pg.execute(f"""
                SELECT sm.trade_date, cl.name AS concept_name, SUM(sm.main_inflow) AS main_inflow
                FROM concept_member cm
                JOIN stock_money_flow sm ON cm.ts_code = sm.ts_code
                    AND sm.trade_date >= %s AND sm.trade_date <= %s
                JOIN concept_list cl ON cm.concept_code = cl.code
                WHERE cl.name IN ({ph})
                GROUP BY sm.trade_date, cl.name
                ORDER BY cl.name, sm.trade_date
            """, [earliest, latest] + concept_names).fetchall()
        finally:
            pg.close()

        from collections import defaultdict
        by_concept = defaultdict(lambda: defaultdict(float))
        for r in rows:
            by_concept[r[1]][str(r[0])] = float(r[2] or 0)

        colors = ['#f87171','#38bdf8','#34d399','#fb923c','#a78bfa',
                  '#facc15','#f472b6','#2dd4bf','#eab308','#818cf8']

        series = []
        for idx, name in enumerate(concept_names):
            data = [round(by_concept[name].get(d, 0), 1) for d in date_list]
            series.append({
                "name": name,
                "data": data,
                "color": colors[idx % len(colors)],
            })

        return jsonify({
            "dates": date_list,
            "series": series,
            "unit": "万元（后端存储，前端展示为亿）",
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/money-flow/stock')
def api_money_flow_stock():
    """指定日期个股主力资金流排名（PG stock_money_flow + resolve_name + DuckDB pct_chg）。"""
    date_str = request.args.get('date')
    try:
        pg = psycopg.connect(settings.pg_dsn)
        try:
            if not date_str:
                date_str = pg.execute(
                    "SELECT MAX(trade_date) FROM stock_money_flow"
                ).fetchone()[0]
                date_str = str(date_str)
            rows = pg.execute("""
                SELECT ts_code, name, main_inflow, pct_chg
                FROM stock_money_flow
                WHERE trade_date = %s
                ORDER BY main_inflow DESC NULLS LAST
            """, [date_str]).fetchall()
        finally:
            pg.close()

        # 从 DuckDB 批量获取涨跌幅
        db = get_db()
        try:
            ts_codes = ["{}.SH".format(r[0].split('.')[1]) if '.SH' in (r[0] or '') else
                        "{}.SZ".format(r[0].split('.')[1]) if '.SZ' in (r[0] or '') else r[0]
                        for r in rows]
            # pg 的 ts_code 是 002396.SZ 格式，直接可用
            ts_codes_set = list(set(r[0] for r in rows if r[0]))
            if ts_codes_set:
                ph = ','.join(['?' for _ in ts_codes_set])
                chg_rows = db.execute(
                    f"""SELECT ts_code, pct_chg FROM daily_bar
                        WHERE trade_date = ? AND ts_code IN ({ph})""",
                    [date_str] + ts_codes_set
                ).fetchall()
                chg_map = {r[0]: float(r[1] or 0) for r in chg_rows}
            else:
                chg_map = {}
        finally:
            db.close()

        stocks = []
        for r in rows:
            ts_code, name, main, pct_chg_pg = r
            code = ts_code.replace('.SH','').replace('.SZ','') if ts_code else ''
            display_name = _resolve_name(code, name) if name and name != code else resolve_name(str(code))
            chg = chg_map.get(ts_code, pct_chg_pg or 0)
            stocks.append({
                "code": code,
                "name": display_name,
                "main_inflow": round(main or 0, 2),  # 万元
                "pct_chg": round(chg, 2),
            })

        return jsonify({
            "date": date_str,
            "stocks": stocks,
            "total": len(stocks),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500



@app.route('/live')
def live_page():
    """实盘组合跟踪"""
    return render_template('live.html')


@app.route('/api/intraday/summary')
def api_intraday_summary():
    """盘中快照摘要 — 从 DuckDB 三表查询最新 snapshot。"""
    db = get_db()
    try:
        # Latest fetch_time from spot
        latest = db.execute(
            "SELECT MAX(fetch_time) FROM intraday_spot"
        ).fetchone()[0]
        if latest is None:
            return jsonify({"fetch_time": None, "message": "无盘中数据"})

        latest_dt = str(latest)

        # Market breadth from spot
        breadth = db.execute("""
            SELECT
                COUNT(CASE WHEN pct_chg > 0 THEN 1 END) AS up,
                COUNT(CASE WHEN pct_chg < 0 THEN 1 END) AS down,
                COUNT(CASE WHEN pct_chg = 0 OR pct_chg IS NULL THEN 1 END) AS flat
            FROM intraday_spot WHERE fetch_time = ?
        """, (latest,)).fetchone()

        # Top gainers / losers
        top_gainers = db.execute("""
            SELECT ts_code, name, pct_chg, close
            FROM intraday_spot WHERE fetch_time = ?
            ORDER BY pct_chg DESC NULLS LAST LIMIT 10
        """, (latest,)).fetchall()
        top_losers = db.execute("""
            SELECT ts_code, name, pct_chg, close
            FROM intraday_spot WHERE fetch_time = ?
            ORDER BY pct_chg ASC NULLS LAST LIMIT 10
        """, (latest,)).fetchall()

        # Stock fund flow top inflow / outflow
        top_inflow = db.execute("""
            SELECT ts_code, name, main_inflow, main_inflow_pct, close
            FROM intraday_fund_flow ORDER BY fetch_time DESC, main_inflow DESC NULLS LAST LIMIT 10
        """).fetchall()

        top_outflow = db.execute("""
            SELECT ts_code, name, main_inflow, main_inflow_pct, close
            FROM intraday_fund_flow ORDER BY fetch_time DESC, main_inflow ASC NULLS LAST LIMIT 10
        """).fetchall()

        # Sector flow
        sector_flow = db.execute("""
            SELECT sector_name, sector_type, pct_chg, main_inflow, main_inflow_pct
            FROM intraday_sector_flow
            ORDER BY fetch_time DESC, main_inflow DESC NULLS LAST LIMIT 20
        """).fetchall()

        # Shanghai index
        sh_row = db.execute(
            "SELECT close, pct_chg FROM intraday_spot WHERE ts_code='000001.SH' ORDER BY fetch_time DESC LIMIT 1"
        ).fetchone()

        return jsonify({
            "fetch_time": latest_dt,
            "market_breadth": {
                "up": breadth[0] or 0, "down": breadth[1] or 0, "flat": breadth[2] or 0,
            },
            "shanghai_index": {
                "close": float(sh_row[0]) if sh_row and sh_row[0] else None,
                "pct_chg": float(sh_row[1]) if sh_row and sh_row[1] else None,
            } if sh_row else None,
            "top_gainers": [{"code": r[0], "name": r[1], "pct_chg": float(r[2]) if r[2] else 0,
                             "close": float(r[3]) if r[3] else 0} for r in top_gainers],
            "top_losers": [{"code": r[0], "name": r[1], "pct_chg": float(r[2]) if r[2] else 0,
                            "close": float(r[3]) if r[3] else 0} for r in top_losers],
            "top_inflow": [{"code": r[0], "name": r[1],
                            "main_inflow": float(r[2]) if r[2] else 0,
                            "main_inflow_pct": float(r[3]) if r[3] else 0,
                            "close": float(r[4]) if r[4] else 0} for r in top_inflow],
            "top_outflow": [{"code": r[0], "name": r[1],
                             "main_inflow": float(r[2]) if r[2] else 0,
                             "main_inflow_pct": float(r[3]) if r[3] else 0,
                             "close": float(r[4]) if r[4] else 0} for r in top_outflow],
            "sector_flow": [{"name": r[0], "type": r[1],
                             "pct_chg": float(r[2]) if r[2] else 0,
                             "main_inflow": float(r[3]) if r[3] else 0,
                             "main_inflow_pct": float(r[4]) if r[4] else 0} for r in sector_flow],
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/live/summary')
def api_live_summary():
    """JQ 实盘组合总览：净值 + 交易 + 持仓 + 订单。"""
    db = get_db()
    try:
        nav_rows = db.execute(
            "SELECT date, cash, position_value, total, total_return, positions"
            " FROM jq_live_nav WHERE strategy_id='caimadama' ORDER BY date"
        ).fetchall()
        nav = [{"date": str(r[0]), "cash": round(float(r[1] or 0), 2),
                "position_value": round(float(r[2] or 0), 2),
                "total": round(float(r[3] or 0), 2),
                "total_return": round(float(r[4] or 0) * 100, 2),
                "positions": r[5]} for r in nav_rows]

        trades = db.execute(
            "SELECT date, code, name, action, price, shares, amount, pnl, pnl_pct, reason"
            " FROM jq_live_trades WHERE strategy_id='caimadama' ORDER BY date DESC"
        ).fetchall()
        trade_list = [{"date": str(r[0]), "code": r[1], "name": r[2], "action": r[3],
                       "price": float(r[4] or 0), "shares": r[5],
                       "amount": round(float(r[6] or 0), 2),
                       "pnl": round(float(r[7] or 0), 2),
                       "pnl_pct": round(float(r[8] or 0), 2), "reason": r[9] or ""}
                      for r in trades]

        # 当前持仓 → 从 positions 表查 JQ 条目，用 daily_bar.close 刷新 current_price
        holding = db.execute(
            "SELECT code, name, shares, buy_price, current_price, buy_date"
            " FROM positions WHERE status='holding' AND strategy='JQ_CAIMADAMA' ORDER BY code"
        ).fetchall()
        # 批量刷新最新价格
        codes = list(set(r[0] for r in holding))
        price_map = {}
        if codes:
            ts_codes = [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in codes]
            ph = ",".join(["?" for _ in ts_codes])
            p_rows = db.execute(
                f"""SELECT ts_code, close FROM daily_bar
                     WHERE trade_date = (SELECT MAX(trade_date) FROM daily_bar)
                       AND ts_code IN ({ph})""",
                ts_codes,
            ).fetchall()
            price_map = {r[0].split(".")[0]: float(r[1]) for r in p_rows if r[1] and r[1] > 0}
        holds = [{"code": r[0], "name": r[1], "shares": r[2],
                  "buy_price": float(r[3] or 0),
                  "current_price": price_map.get(r[0], float(r[4] or 0)),
                  "buy_date": str(r[5]),
                  "pnl_pct": round((price_map.get(r[0], float(r[4] or 0)) - float(r[3] or 0)) / float(r[3] or 1) * 100, 2)}
                 for r in holding]

        orders = db.execute(
            "SELECT trade_date, code, name, action, price, shares, status, reason"
            " FROM order_queue WHERE strategy='caimadama' ORDER BY trade_date, status"
        ).fetchall()
        order_list = [{"trade_date": str(r[0]), "code": r[1], "name": r[2], "action": r[3],
                       "price": float(r[4] or 0), "shares": r[5], "status": r[6],
                       "reason": r[7] or ""} for r in orders]

        return jsonify({"nav": nav, "trades": trade_list, "holdings": holds, "orders": order_list})
    finally:
        db.close()


@app.route('/risk')
def risk_page():
    """风控仪表盘"""
    return render_template('risk.html')


@app.route('/api/risk/summary')
def api_risk_summary():
    """风控总览：集中度 + 回撤 + 止损预警。"""
    from risk.rules import RiskEngine
    db = get_db()
    try:
        holding = db.execute(
            "SELECT code, name, shares, buy_price, current_price, buy_date, strategy"
            " FROM positions WHERE status='holding' ORDER BY strategy, code"
        ).fetchall()
        if not holding:
            return jsonify({"error": "无持仓数据"})

        engine = RiskEngine()
        positions_dict = {}
        total_value = 0.0
        detail = []
        for r in holding:
            code, name, shares, buy_p, cur_p, buy_d, strat = r
            shares_i = int(shares or 0)
            bp = float(buy_p or 0)
            cp = float(cur_p or 0)
            mv = shares_i * cp
            total_value += mv
            pnl_pct = (cp - bp) / bp * 100 if bp > 0 else 0
            stopped, reason = engine.check_stop_loss(bp, cp)
            detail.append({
                "code": code, "name": name, "strategy": strat or "",
                "shares": shares_i, "buy_price": round(bp, 2),
                "current_price": round(cp, 2), "market_value": round(mv, 2),
                "pnl_pct": round(pnl_pct, 2), "stop_loss_warn": stopped,
                "stop_reason": reason, "buy_date": str(buy_d),
            })
            positions_dict[code] = {"shares": shares_i, "market_value": mv, "strategy": strat or ""}

        # 集中度
        max_single_pct = max((d["market_value"] / total_value * 100) for d in detail) if total_value > 0 else 0
        strat_conc = {}
        for d in detail:
            s = d["strategy"]; strat_conc[s] = strat_conc.get(s, 0) + d["market_value"]
        max_strat = max(strat_conc, key=strat_conc.get) if strat_conc else ""

        nr = db.execute("SELECT total_return FROM jq_live_nav WHERE strategy_id='caimadama' ORDER BY date DESC LIMIT 1").fetchone()
        current_return = float(nr[0] or 0) * 100 if nr else 0

        return jsonify({
            "total_positions": len(detail),
            "total_value": round(total_value, 2),
            "max_single_pct": round(max_single_pct, 1),
            "max_strategy": max_strat,
            "strategy_concentration": {k: round(v / max(total_value, 1) * 100, 1) for k, v in strat_conc.items()},
            "current_return_pct": round(current_return, 2),
            "holdings": detail,
        })
    finally:
        db.close()


@app.route('/strategy-editor')
def strategy_editor_page():
    """策略代码编辑器"""
    return render_template('strategy_editor.html')


@app.route('/api/strategy-editor/list')
def api_strategy_list():
    """列出所有可编辑的策略源文件。"""
    strategies_dir = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'jq')
    files = []
    if os.path.isdir(strategies_dir):
        for fn in sorted(os.listdir(strategies_dir)):
            if fn.endswith('.py') and not fn.startswith('_'):
                fp = os.path.join(strategies_dir, fn)
                size = os.path.getsize(fp)
                with open(fp) as f:
                    first_line = f.readline().strip()
                files.append({"name": fn, "size": size, "summary": first_line.strip('"').strip("'")})
    return jsonify({"strategies": files})


@app.route('/api/strategy-editor/<name>', methods=['GET', 'PUT', 'DELETE'])
def api_strategy_code(name: str):
    """读/写/删策略文件内容。"""
    strategies_dir = os.path.join(os.path.dirname(__file__), '..', 'strategies', 'jq')
    safe_name = os.path.basename(name)
    if not safe_name.endswith('.py'):
        return jsonify({"error": "仅支持 .py 策略文件"}), 400
    fp = os.path.join(strategies_dir, safe_name)

    if request.method == 'DELETE':
        if not os.path.isfile(fp):
            return jsonify({"error": f"策略文件 {safe_name} 不存在"}), 404
        os.rename(fp, fp + ".deleted." + datetime.now().strftime("%Y%m%d%H%M%S"))
        return jsonify({"deleted": True, "name": safe_name})

    if not os.path.isfile(fp):
        if request.method == 'PUT':
            # 新建文件
            data = request.get_json(force=True)
            content = data.get("content", "")
            with open(fp, "w") as f:
                f.write(content)
            return jsonify({"name": safe_name, "saved": True, "backup": None})
        return jsonify({"error": f"策略文件 {safe_name} 不存在"}), 404

    if request.method == 'GET':
        with open(fp) as f:
            return jsonify({"name": safe_name, "content": f.read()})
    else:  # PUT
        data = request.get_json(force=True)
        if "content" not in data:
            return jsonify({"error": "缺少 content 字段"}), 400
        # 备份
        backup = fp + ".bak"
        if os.path.exists(fp):
            os.rename(fp, backup)
        with open(fp, "w") as f:
            f.write(data["content"])
        # 同步清缓存中的 loader（下次回测用新代码）
        if safe_name in sys.modules:
            del sys.modules[safe_name]
        return jsonify({"name": safe_name, "saved": True, "backup": os.path.basename(backup)})


@app.route('/api/strategy-editor/resonance')
def api_strategy_resonance():
    """策略共振 — 当日多策略信号交叉分析。

    返回:
      { date, buy_resonance:int, sell_resonance:int,
        details: [{code, name, strategies[], signal_type, score_s1}, ...] }
    共振定义: 同一股票在同一天被 ≥2 个策略触发信号。
    """
    db = get_db()
    try:
        latest_date = db.execute(
            "SELECT MAX(date) FROM daily_signals"
        ).fetchone()[0]
        if latest_date is None:
            return jsonify({"error": "无信号数据"})

        # 读所有信号列
        buy_cols = [
            ("signal_buy_b1", "B1"), ("signal_buy_b2", "B2"),
            ("signal_buy_blk", "BLK"), ("signal_buy_blkB2", "BLKB2"),
            ("signal_buy_dz30", "DZ30"), ("signal_buy_scb", "SCB"),
        ]
        sell_cols = [
            ("signal_sell_b1", "B1_SELL"), ("signal_sell_b2", "B2_SELL"),
            ("signal_sell_blk", "BLK_SELL"), ("signal_sell_blkB2", "BLKB2_SELL"),
            ("signal_sell_dz30", "DZ30_SELL"), ("signal_sell_scb", "SCB_SELL"),
            ("signal_s1_full", "S1_FULL"), ("signal_s1_half", "S1_HALF"),
        ]

        # 加载当天所有信号
        signals = db.execute(
            "SELECT code, name, score_s1, "
            + ", ".join([c[0] for c in buy_cols + sell_cols])
            + " FROM daily_signals WHERE date = ?",
            [latest_date.isoformat()],
        ).fetchall()

        if not signals:
            return jsonify({"error": "当天无信号数据", "date": str(latest_date)})

        col_names = ["code", "name", "score_s1"] + [c[0] for c in buy_cols + sell_cols]

        details = []
        buy_resonance = 0
        sell_resonance = 0

        for row in signals:
            rec = dict(zip(col_names, row))
            code = rec["code"]
            name_val = rec.get("name", code) or code
            score_s1 = float(rec.get("score_s1", 0) or 0)

            # 收集触发策略
            triggered_buy = [abbr for col, abbr in buy_cols if rec.get(col)]
            triggered_sell = [abbr for col, abbr in sell_cols if rec.get(col)]

            # 买入共振: ≥2 个策略同时触发
            if len(triggered_buy) >= 2:
                buy_resonance += 1
                details.append({
                    "code": code, "name": str(name_val),
                    "strategies": triggered_buy,
                    "signal_type": "buy",
                    "score_s1": score_s1,
                })

            # 卖出共振: ≥2 个策略同时触发卖出（或 S1_FULL + 策略卖出）
            if len(triggered_sell) >= 2:
                sell_resonance += 1
                details.append({
                    "code": code, "name": str(name_val),
                    "strategies": triggered_sell,
                    "signal_type": "sell",
                    "score_s1": score_s1,
                })

        details.sort(key=lambda x: len(x["strategies"]), reverse=True)
        return jsonify({
            "date": str(latest_date),
            "buy_resonance": buy_resonance,
            "sell_resonance": sell_resonance,
            "details": details,
        })
    finally:
        db.close()


if __name__ == '__main__':
    # 习惯用 scripts/run_web.py 启动以获得正确的 sys.path 和 cwd。
    # 本块留作直接启动的备选。
    import os as _os, sys as _sys
    _project_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)
    _os.chdir(_project_root)

    _template_dir = _os.path.join(_os.path.dirname(__file__), 'templates')
    _os.makedirs(_template_dir, exist_ok=True)

    print("启动Dashboard服务: http://localhost:5004")
    _debug = _os.environ.get('WEB_DEBUG', '0') == '1'
    app.run(debug=_debug, port=5004, host='0.0.0.0')
