"""飞书告警公用模块 — 供盘中采集、风控检查等复用。

Usage:
    from utils.feishu_alert import send_alert_card
    send_alert_card("盘中预警", [{"type": "index_drop", "msg": "上证跌超2%"}])
"""

from __future__ import annotations

import requests

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("feishu_alert")

TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
DEFAULT_RECEIVE_ID = "ou_113faaff836977aa0e1efb1a67707e0b"
DEFAULT_RECEIVE_TYPE = "open_id"

_token_cache: tuple[str, float] | None = None


def _get_tenant_token() -> str:
    """Obtain tenant access token with in-process caching."""
    global _token_cache
    import time as _time

    if _token_cache and _time.monotonic() - _token_cache[1] < 3600:
        return _token_cache[0]

    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET not configured")

    resp = requests.post(
        TENANT_TOKEN_URL,
        json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Feishu token error: {data.get('msg', 'unknown')}")
    token = data["tenant_access_token"]
    _token_cache = (token, _time.monotonic())
    return token


def send_alert_card(
    title: str,
    alerts: list[dict],
    receive_id: str = DEFAULT_RECEIVE_ID,
    receive_id_type: str = DEFAULT_RECEIVE_TYPE,
) -> bool:
    """Send a simple alert card to Feishu.

    Args:
        title: Card title (e.g. "盘中预警")
        alerts: List of {"type": "...", "msg": "..."} dicts
        receive_id: Feishu user/chat ID
        receive_id_type: "open_id" | "chat_id" | "user_id" | "union_id"

    Returns:
        True if sent successfully.
    """
    if not alerts:
        return True

    try:
        token = _get_tenant_token()
    except Exception as e:
        logger.error(f"Feishu auth failed: {e}")
        return False

    # Build card content
    alert_lines: list[dict] = []
    alert_type_emoji = {
        "index_drop": "📉",
        "sector_inflow": "🔥",
        "sector_outflow": "💧",
    }
    for a in alerts:
        emoji = alert_type_emoji.get(a.get("type", ""), "⚠️")
        alert_lines.append({"tag": "text", "text": f"{emoji} {a['msg']}"})

    card = {
        "header": {
            "title": {"tag": "plain_text", "content": f"⚠️ {title}"},
            "template": "red" if any(a["type"] == "index_drop" for a in alerts) else "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": "\n".join(
                    f"**{a.get('type', 'alert')}**\n{a.get('msg', '')}"
                    for a in alerts
                ),
            }
        ],
    }

    payload = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": requests.utils.json_dumps(card),
    }

    try:
        resp = requests.post(
            f"{MESSAGE_SEND_URL}?receive_id_type={receive_id_type}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        data = resp.json()
        if data.get("code") == 0:
            logger.info(f"Alert sent: {len(alerts)} items")
            return True
        else:
            logger.error(f"Feishu send error: {data.get('msg', 'unknown')}")
            return False
    except Exception as e:
        logger.error(f"Feishu send failed: {e}")
        return False
