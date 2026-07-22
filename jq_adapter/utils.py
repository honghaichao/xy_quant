# coding=utf-8
"""
utils.py — 代码转换、日期工具、g 对象持久化
"""

import os
import pickle
from datetime import datetime, date
from typing import Union


# ============================================================
# 代码标准化
# ============================================================
def normalize_code(code: str) -> str:
    """
    标准化证券代码为 xy_quant 格式（如 000001.SZ）。

    支持的输入格式：
      - 6 位纯数字 "000001"  → "000001.SZ"
      - 聚宽格式 "000001.XSHE" → "000001.SZ"
      - Tushare 格式 "000001.SZ" → "000001.SZ"
    """
    if not code:
        return code

    code = str(code).strip()

    if "." in code and len(code.split(".")[1]) in (2, 3):
        # Already in xy_quant/tushare format
        return code.upper() if code[-2:] in ("SH", "SZ", "BJ") else code

    if code.isdigit() and len(code) == 6:
        if code.startswith("6") or code.startswith("688"):
            return f"{code}.SH"
        elif code.startswith("8"):
            return f"{code}.BJ"
        else:
            return f"{code}.SZ"

    if "." in code:
        symbol, suffix = code.split(".")
        suffix = suffix.upper()
        if suffix == "XSHE":
            return f"{symbol}.SZ"
        elif suffix == "XSHG":
            return f"{symbol}.SH"
        elif suffix == "BJ":
            return f"{symbol}.BJ"

    return code


def to_jq_code(code: str) -> str:
    """xy_quant 代码 → 聚宽格式（000001.SZ → 000001.XSHE）"""
    code = normalize_code(code)
    if code.endswith(".SZ"):
        return code.replace(".SZ", ".XSHE")
    elif code.endswith(".SH"):
        return code.replace(".SH", ".XSHG")
    elif code.endswith(".BJ"):
        return code.replace(".BJ", ".BJ")
    return code


def get_code_part(code: str) -> str:
    """获取股票代码的纯数字部分。"""
    if "." in code:
        return code.split(".")[0]
    return code


# ============================================================
# 市场判断
# ============================================================
def is_kcb_code(code: str) -> bool:
    """是否为科创板（688xxx.SH）"""
    code = normalize_code(code)
    return code.startswith("688") and code.endswith(".SH")


def is_cyb_code(code: str) -> bool:
    """是否为创业板（300xxx.SZ）"""
    code = normalize_code(code)
    return code.startswith("300") and code.endswith(".SZ")


# ============================================================
# 日期工具
# ============================================================
def parse_date(date_str: Union[str, datetime, date]) -> datetime:
    """解析多种日期格式 -> datetime"""
    if isinstance(date_str, datetime):
        return date_str
    if isinstance(date_str, date):
        return datetime.combine(date_str, datetime.min.time())
    if isinstance(date_str, int):
        date_str = str(date_str)
    date_str = str(date_str).replace("-", "")
    if len(date_str) == 8:
        return datetime.strptime(date_str, "%Y%m%d")
    raise ValueError(f"无法解析日期: {date_str}")


def format_date(dt: Union[datetime, str], fmt: str = "%Y-%m-%d") -> str:
    """格式化日期为字符串"""
    if isinstance(dt, str):
        return dt
    return dt.strftime(fmt)


def format_date_ymd(dt: Union[datetime, str]) -> str:
    """日期 -> YYYYMMDD"""
    if isinstance(dt, str) and len(dt) == 8:
        return dt
    return format_date(dt, "%Y%m%d")


# ============================================================
# g 对象持久化
# ============================================================
class GStorage:
    """策略全局变量持久化"""

    @staticmethod
    def cache_dir() -> str:
        d = os.path.join(os.path.dirname(__file__), "cache")
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def save(data: dict, strategy_name: str = "default") -> None:
        filepath = os.path.join(GStorage.cache_dir(), f"g_{strategy_name}.pkl")
        try:
            with open(filepath, "wb") as f:
                pickle.dump(data, f)
        except Exception as e:
            print(f"[jq_adapter] g 对象保存失败: {e}")

    @staticmethod
    def load(strategy_name: str = "default") -> dict:
        filepath = os.path.join(GStorage.cache_dir(), f"g_{strategy_name}.pkl")
        if os.path.exists(filepath):
            try:
                with open(filepath, "rb") as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"[jq_adapter] g 对象加载失败: {e}")
        return {}

    @staticmethod
    def clear(strategy_name: str = "default") -> None:
        filepath = os.path.join(GStorage.cache_dir(), f"g_{strategy_name}.pkl")
        if os.path.exists(filepath):
            os.remove(filepath)
