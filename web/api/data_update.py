"""Flask API - 数据更新接口 (适配 xy_quant 数据运维体系)."""
import os
import subprocess
import threading
from datetime import datetime

import duckdb
from flask import Blueprint, jsonify, request

from config.settings import settings

data_update_bp = Blueprint("data_update", __name__, url_prefix="/api/data-update")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.abspath(settings.duckdb_path)

update_tasks: dict[str, dict] = {}


def run_update_task(
    task_id: str, data_type: str, date_str: str | None = None,
    start_date: str | None = None, end_date: str | None = None,
) -> None:
    """在后台线程中运行数据更新任务。"""
    update_tasks[task_id] = {"status": "running", "started_at": datetime.now().isoformat()}
    python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")

    # Map data types to xy_quant scripts
    script_map = {
        "daily": "scripts/update_daily_bar.py",
        "daily_basic": "scripts/update_daily_basic.py",
        "adj_factor": "scripts/update_adj_factor.py",
        "index_daily": "scripts/update_index_daily.py",
        "limit_list": "scripts/update_limit_list.py",
        "money_flow": "scripts/update_money_flow.py",
        "top_list": "scripts/update_top_list.py",
        "margin": "scripts/update_margin.py",
        "hk_hold": "scripts/update_hk_hold.py",
        "suspend": "scripts/update_suspend.py",
        "finance": "scripts/update_finance.py",
        "member": "scripts/update_member.py",
        "calendar": "scripts/update_calendar.py",
        "basic": "scripts/update_basic.py",
        "all": "scripts/update_all.py",
    }

    script = script_map.get(data_type, "scripts/backfill_day.py")
    cmd = [python, os.path.join(PROJECT_ROOT, script)]
    if date_str:
        cmd.extend(["--date", date_str])
    if start_date:
        cmd.extend(["--start", start_date])
    if end_date:
        cmd.extend(["--end", end_date])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        update_tasks[task_id] = {
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-1000:],
            "returncode": result.returncode,
            "finished_at": datetime.now().isoformat(),
        }
    except subprocess.TimeoutExpired:
        update_tasks[task_id] = {"status": "timeout", "finished_at": datetime.now().isoformat()}
    except Exception as e:
        update_tasks[task_id] = {"status": "error", "error": str(e),
                                  "finished_at": datetime.now().isoformat()}


@data_update_bp.route("/status", methods=["GET"])
def data_update_status() -> tuple:
    """获取最新数据覆盖状态。"""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        daily = conn.execute(
            "SELECT MAX(trade_date), COUNT(*) FROM daily_bar"
        ).fetchone()
        basic = conn.execute(
            "SELECT MAX(trade_date), COUNT(*) FROM daily_basic"
        ).fetchone()
        return jsonify({
            "daily_bar": {"latest_date": str(daily[0]) if daily else None, "rows": daily[1] if daily else 0},
            "daily_basic": {"latest_date": str(basic[0]) if basic else None, "rows": basic[1] if basic else 0},
        })
    finally:
        conn.close()


@data_update_bp.route("/update", methods=["POST"])
def trigger_update() -> tuple:
    """触发数据更新任务。"""
    data = request.get_json() or {}
    task_id = data.get("task_id", f"update_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    data_type = data.get("data_type", "daily")
    date_str = data.get("date")

    t = threading.Thread(
        target=run_update_task,
        args=(task_id, data_type, date_str),
        daemon=True,
    )
    t.start()
    return jsonify({"task_id": task_id, "status": "started"})


@data_update_bp.route("/task/<task_id>", methods=["GET"])
def task_status(task_id: str) -> tuple:
    """查询任务状态。"""
    if task_id not in update_tasks:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(update_tasks[task_id])
