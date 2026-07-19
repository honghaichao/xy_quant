"""数据源抽象接口。所有数据源(Tushare/AKShare/Wind/...)必须实现。"""
from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class IDataSource(ABC):
    """数据源接口。"""

    name: str

    @abstractmethod
    def fetch_daily_bar(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """日线行情。"""

    @abstractmethod
    def fetch_minute_bar(
        self,
        ts_code: str,
        start_date: date,
        end_date: date,
        freq: str = "1min",
    ) -> pd.DataFrame:
        """分钟线行情。"""

    @abstractmethod
    def fetch_adj_factor(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """复权因子。"""

    @abstractmethod
    def fetch_daily_basic(
        self,
        ts_code: str | list[str] | None = None,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """每日指标。"""

    @abstractmethod
    def fetch_index_daily(
        self,
        ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """指数日线。"""

    @abstractmethod
    def fetch_limit_pool(self, trade_date: date, kind: str = "U") -> pd.DataFrame:
        """涨跌停池。"""

    @abstractmethod
    def fetch_stock_basic(self) -> pd.DataFrame:
        """股票基础信息。"""

    @abstractmethod
    def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        """交易日历。"""

    @abstractmethod
    def fetch_stock_suspend(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame:
        """停复牌。"""

    @abstractmethod
    def fetch_income(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        """利润表。"""

    @abstractmethod
    def fetch_balancesheet(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        """资产负债表。"""

    @abstractmethod
    def fetch_cashflow(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        """现金流量表。"""

    @abstractmethod
    def fetch_fina_indicator(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        """财务指标。"""

    @abstractmethod
    def fetch_dividend(self, ts_code: str) -> pd.DataFrame:
        """分红送股。"""

    @abstractmethod
    def fetch_top_list(self, trade_date: date) -> pd.DataFrame:
        """龙虎榜。"""

    @abstractmethod
    def fetch_margin_detail(self, trade_date: date) -> pd.DataFrame:
        """融资融券。"""

    @abstractmethod
    def fetch_stk_holdertrade(
        self, ts_code: str | None = None, ann_date: date | None = None
    ) -> pd.DataFrame:
        """股东增减持。"""

    @abstractmethod
    def fetch_hk_hold(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame:
        """北向持股。"""

    @abstractmethod
    def fetch_concept_money_flow(self, trade_date: date) -> pd.DataFrame:
        """概念资金流。"""

    @abstractmethod
    def fetch_industry_money_flow(self, trade_date: date) -> pd.DataFrame:
        """行业资金流。"""

    @abstractmethod
    def fetch_stock_money_flow(self, trade_date: date) -> pd.DataFrame:
        """个股资金流。"""

    @abstractmethod
    def fetch_concept_list(self) -> pd.DataFrame:
        """概念列表。"""

    @abstractmethod
    def fetch_concept_member(self, concept_code: str) -> pd.DataFrame:
        """概念成分。"""

    @abstractmethod
    def fetch_industry_list(self) -> pd.DataFrame:
        """行业列表。"""

    @abstractmethod
    def fetch_industry_member(self, industry_code: str) -> pd.DataFrame:
        """行业成分。"""

    @abstractmethod
    def fetch_index_weight(
        self, index_code: str, trade_date: date | None = None
    ) -> pd.DataFrame:
        """指数权重。"""

    def supports(self, capability: str) -> bool:
        """声明该数据源支持哪些数据。"""
        return False
