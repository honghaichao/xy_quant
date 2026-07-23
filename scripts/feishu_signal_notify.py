"""Feishu card-based signal notification.

Sends daily scan results as interactive cards via Feishu IM API.

Usage:
    .venv/bin/python scripts/feishu_signal_notify.py                    # latest date
    .venv/bin/python scripts/feishu_signal_notify.py --date 20260716   # specific date
    .venv/bin/python scripts/feishu_signal_notify.py --dry-run          # print only
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json

import duckdb
import requests

from config.settings import settings
from utils.logger import get_logger
from utils.stock_name import load_name_map, resolve_name

logger = get_logger("feishu_signal_notify")

TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

# ── card colour helpers ──────────────────────────────────────────────
CARD_GREEN = "green"
CARD_RED = "red"
CARD_BLUE = "blue"
CARD_GREY = "grey"

STRATEGY_LABEL: dict[str, str] = {
    "B1": "🏔️ B1 天宫低吸",
    "B2": "🚀 B2 天宫追涨",
    "BLK": "⚡ BLK 暴力K",
    "BLKB2": "🔥 BLKB2 组合",
    "SCB": "🌪️ SCB 沙尘暴",
    "DZ30": "📌 DZ30 单针30",
    "DL": "🔻 DL",
}

STRATEGY_SORT = ["B1", "B2", "BLK", "BLKB2", "SCB", "DZ30", "DL"]


def get_tenant_token() -> str:
    """Obtain a tenant access token (cached to avoid rate limits)."""
    resp = requests.post(
        TENANT_TOKEN_URL,
        json={
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret,
        },
        timeout=10,
    )
    payload = resp.json()
    if payload.get("code", 0) != 0:
        raise RuntimeError(f"Feishu token error: {payload}")
    return payload["tenant_access_token"]


def fetch_signals(target_date: str) -> dict:
    """Fetch buy signals from daily_signals for a single date."""
    db = duckdb.connect(str(settings.duckdb_path_abs), read_only=True)
    try:
        td = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
        cols = [desc[0] for desc in db.execute("DESCRIBE daily_signals").fetchall()]
        rows = db.execute(
            "SELECT * FROM daily_signals WHERE date = ?", [td]
        ).fetchall()
        if not rows:
            return {"date": td, "total": 0, "by_strategy": {}, "buy_list": []}

        # Load names (now uses shared cache)
        name_map = load_name_map()

        buy_signal_cols = [c for c in cols if c.startswith("signal_buy_")]
        sell_signal_cols = [
            c for c in cols
            if c in ("signal_s1_full", "signal_s1_half", "signal_跌破多空线", "signal_止损")
        ]

        by_strategy: dict[str, list[dict]] = {}
        buy_list: list[dict] = []
        sell_list: list[dict] = []
        all_with_signal = 0

        for row in rows:
            rec = dict(zip(cols, row))
            code = str(rec.get("code", ""))
            name = resolve_name(code, name_map)
            close = rec.get("close")
            change_pct = rec.get("change_pct")
            close = rec.get("close")
            change_pct = rec.get("change_pct")

            for col in buy_signal_cols:
                if rec.get(col):
                    abbr = col.replace("signal_buy_", "").upper()
                    score_col = f"score_{col.replace('signal_buy_', '')}"
                    score = float(rec.get(score_col, 0) or 0)
                    item = {
                        "code": code, "name": name,
                        "close": round(close, 2) if close else None,
                        "change_pct": round(change_pct, 2) if change_pct else None,
                        "score": round(score, 1),
                    }
                    by_strategy.setdefault(abbr, []).append(item)
                    buy_list.append({**item, "strategy": abbr})

            for col in sell_signal_cols:
                if rec.get(col):
                    sell_list.append({"code": code, "name": name})

        # Sort buy_list by score desc
        buy_list.sort(key=lambda x: x["score"], reverse=True)

        # ── 查询 AI 分析结果 ──
        agent_decisions: dict[str, dict] = {}
        try:
            from agent.adapters.result_adapter import get_daily_agent_decisions
            agent_decisions = get_daily_agent_decisions(td)
        except Exception:
            pass

        return {
            "date": td,
            "total": len(rows),
            "signals_with_buy": len(set(b["code"] for b in buy_list)),
            "signals_with_sell": len(sell_list),
            "by_strategy": {k: sorted(v, key=lambda x: x["score"], reverse=True)
                            for k, v in sorted(by_strategy.items())},
            "buy_list": buy_list,
            "sell_list": sell_list,
            "agent_decisions": agent_decisions,
        }
    finally:
        db.close()


def build_card(data: dict) -> dict:
    """Build a Feishu interactive card message."""
    date_str = data["date"]
    total = data["total"]
    buy_count = data["signals_with_buy"]
    sell_count = data["signals_with_sell"]
    by_strategy = data["by_strategy"]

    # ── header ──
    header = {
        "title": {"tag": "plain_text", "content": f"📊 信号扫描 · {date_str}"},
        "template": CARD_BLUE,
    }

    # ── summary section (rendered first in card) ──
    summary_items: list[dict] = []
    for abbr in STRATEGY_SORT:
        items = by_strategy.get(abbr, [])
        if not items:
            continue
        top3 = ", ".join(
            f"{s['name']}({s['score']})" for s in items[:3]
        )
        summary_items.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"{STRATEGY_LABEL.get(abbr, abbr)}：**{len(items)}** 只 → {top3}",
            },
        })

    markdown_lines = [
        f"全市场 **{total}** 只扫描完毕",
        f"🟢 买入信号 **{buy_count}** 只　🔴 卖出信号 **{sell_count}** 只",
    ]

    # ── top buy list ──
    buy_list = data["buy_list"][:20]
    agent_decisions = data.get("agent_decisions", {})
    if buy_list:
        markdown_lines.append("")
        markdown_lines.append("**🏆 Top 买入信号**")
        markdown_lines.append("")
        if agent_decisions:
            markdown_lines.append("|股票|策略|价格|涨跌%|得分|AI 判断|")
            markdown_lines.append("|---|---|---|---|---|---|")
            for s in buy_list:
                chg = f"{s['change_pct']:+.2f}" if s['change_pct'] is not None else "-"
                ai = agent_decisions.get(s["code"], {})
                ai_label = ""
                if ai:
                    decision = ai.get("final_decision", "")
                    confidence = ai.get("confidence", 0)
                    action = ai.get("action", "")
                    if action or decision:
                        decision_str = action or decision
                        conf_str = f"{confidence:.0%}" if confidence else ""
                        ai_label = f"{decision_str} {conf_str}"
                markdown_lines.append(
                    f"|{s['name']}({s['code']})|{s['strategy']}|{s['close']}|{chg}|{s['score']}|{ai_label}|"
                )
        else:
            markdown_lines.append("|股票|策略|价格|涨跌%|得分|")
            markdown_lines.append("|---|---|---|---|---|")
            for s in buy_list:
                chg = f"{s['change_pct']:+.2f}" if s['change_pct'] is not None else "-"
                markdown_lines.append(
                    f"|{s['name']}({s['code']})|{s['strategy']}|{s['close']}|{chg}|{s['score']}|"
                )

    # ── AI 分析摘要区块 ──
    if agent_decisions:
        ai_has_buy = any(
            d.get("action", "") in ("BUY", "买入") or
            d.get("final_decision", "") in ("买入", "强烈买入")
            for d in agent_decisions.values()
        )
        ai_lines = ["", "**🤖 AI Agent 分析摘要**", ""]
        for code, d in agent_decisions.items():
            name = resolve_name(code, load_name_map())
            ai_label_icon = {
                "BUY": "🟢", "买入": "🟢", "强烈买入": "🟢",
                "HOLD": "🟡", "观望": "🟡",
                "SELL": "🔴", "卖出": "🔴", "卖出/观望": "🔴",
            }.get(d.get("action", d.get("final_decision", "")), "⚪")
            risk_level = d.get("risk_level", "")
            confidence = d.get("confidence", 0)
            ai_lines.append(
                f"{ai_label_icon} **{name}**({code})：{d.get('action', d.get('final_decision', '-'))} "
                f"置信度{confidence:.0%} 风险:{risk_level}"
            )
        if len(agent_decisions) == 0:
            ai_lines.append("当日无 AI 分析结果")
        elements.insert(0, {
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(ai_lines)},
        })
        elements.insert(1, {"tag": "hr"})

    elements: list[dict] = []

    # ── strategy summary (was unused — now rendered) ──
    if summary_items:
        summary_lines = ["**📋 策略信号汇总**", ""]
        for abbr in STRATEGY_SORT:
            items = by_strategy.get(abbr, [])
            if not items:
                continue
            top3 = ", ".join(
                f"{s['name']}({s['score']})" for s in items[:3]
            )
            summary_lines.append(
                f"{STRATEGY_LABEL.get(abbr, abbr)}：**{len(items)}** 只 → {top3}"
            )
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(summary_lines)},
        })
        elements.append({"tag": "hr"})

    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "\n".join(markdown_lines)},
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": header,
        "elements": elements,
    }

    return {
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }


def send_card(token: str, receive_id: str, card: dict, receive_id_type: str = "open_id") -> bool:
    """Send interactive card to Feishu."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "receive_id": receive_id,
        **card,
    }
    resp = requests.post(
        f"{MESSAGE_SEND_URL}?receive_id_type={receive_id_type}",
        headers=headers,
        json=body,
        timeout=15,
    )
    payload = resp.json()
    if payload.get("code", 0) != 0:
        logger.error(f"Feishu send failed: {payload}")
        return False
    logger.info(f"Card sent: message_id={payload.get('data', {}).get('message_id', '?')}")
    return True


def run(
    target_date: str | None = None,
    dry_run: bool = False,
    receive_id: str = "",
    receive_id_type: str = "open_id",
) -> dict:
    """Main entry: fetch signals and send card."""
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        logger.error("FEISHU_APP_ID / FEISHU_APP_SECRET not configured")
        return {"error": "feishu_not_configured"}

    # Default to latest signals date
    if not target_date:
        db = duckdb.connect(str(settings.duckdb_path_abs), read_only=True)
        try:
            row = db.execute("SELECT MAX(date) FROM daily_signals").fetchone()
            if not row or not row[0]:
                logger.error("No signals in daily_signals")
                return {"error": "no_signals"}
            target_date = str(row[0]).replace("-", "")
        finally:
            db.close()

    logger.info(f"Fetching signals for {target_date}")
    data = fetch_signals(target_date)

    if data["total"] == 0:
        logger.warning(f"No signals for {target_date}")
        return {"date": target_date, "total": 0}

    card = build_card(data)

    if dry_run:
        # Pretty-print card instead of sending
        print(json.dumps(card, indent=2, ensure_ascii=False))
        return {"date": target_date, "dry_run": True, **{k: data[k] for k in ("total", "signals_with_buy", "signals_with_sell")}}

    if not receive_id:
        logger.error("No receive_id provided")
        return {"error": "no_receive_id"}

    token = get_tenant_token()
    ok = send_card(token, receive_id, card, receive_id_type)
    return {
        "date": target_date,
        "sent": ok,
        "total": data["total"],
        "buy": data["signals_with_buy"],
        "sell": data["signals_with_sell"],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="飞书信号卡片通知")
    p.add_argument("--date", type=str, default=None, help="YYYYMMDD (default: latest)")
    p.add_argument("--dry-run", action="store_true", help="Print card JSON instead of sending")
    p.add_argument("--receive-id", type=str, default="ou_113faaff836977aa0e1efb1a67707e0b",
                   help="Receive ID (open_id / chat_id)")
    p.add_argument("--receive-id-type", type=str, default="open_id",
                   choices=["open_id", "chat_id", "user_id", "union_id"])
    args = p.parse_args()

    try:
        result = run(
            target_date=args.date,
            dry_run=args.dry_run,
            receive_id=args.receive_id,
            receive_id_type=args.receive_id_type,
        )
        logger.info(f"Done: {json.dumps(result, default=str)}")
        return 0 if result.get("sent") or result.get("dry_run") else 1
    except Exception:
        logger.exception("feishu_signal_notify failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
