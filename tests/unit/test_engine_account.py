"""engine/account.py 单元测试：T+1、费率、取整、加权均价、序列化。"""

from __future__ import annotations

from datetime import date

import pytest

from engine.account import Account, CostConfig, PositionState
from engine.context import Context, G, Portfolio

D1 = date(2026, 7, 13)
D2 = date(2026, 7, 14)


@pytest.fixture
def acct() -> Account:
    return Account(initial_cash=100_000.0, cost=CostConfig())


class TestBuy:
    def test_buy_rounds_down_to_lot(self, acct):
        t = acct.buy("000001", 250, 10.0, D1)
        assert t["shares"] == 200

    def test_buy_below_one_lot_rejected(self, acct):
        assert acct.buy("000001", 99, 10.0, D1) is None

    def test_buy_insufficient_cash_rejected(self, acct):
        assert acct.buy("000001", 20000, 10.0, D1) is None  # 20 万 > 10 万现金
        assert acct.cash == 100_000.0

    def test_buy_commission_and_cash(self, acct):
        t = acct.buy("000001", 100, 10.0, D1)
        assert t["commission"] == pytest.approx(1000 * 0.0003, abs=1e-9)
        assert acct.cash == pytest.approx(100_000 - 1000 * 1.0003)
        assert t["amount"] == pytest.approx(round(1000 * 1.0003, 2))
        assert t["pnl"] == 0.0

    def test_avg_cost_weighted(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        acct.buy("000001", 100, 12.0, D1)
        assert acct.positions["000001"].avg_cost == pytest.approx(11.0)
        assert acct.positions["000001"].total_amount == 200

    def test_min_commission(self):
        acct = Account(100_000.0, CostConfig(min_commission=5.0))
        t = acct.buy("000001", 100, 10.0, D1)  # 佣金 0.3 元 < 5 元
        assert t["commission"] == 5.0


class TestTPlus1:
    def test_same_day_sell_rejected(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        assert acct.positions["000001"].closeable_amount == 0
        assert acct.sell("000001", 100, 11.0, D1) is None

    def test_next_day_sell_allowed(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        acct.settle_new_day(D2)
        t = acct.sell("000001", 100, 11.0, D2)
        assert t is not None and t["shares"] == 100

    def test_partial_unlock(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        acct.settle_new_day(D2)
        acct.buy("000001", 100, 10.0, D2)  # D2 再买 100
        assert acct.positions["000001"].total_amount == 200
        t = acct.sell("000001", 200, 11.0, D2)  # 只能卖 D1 的 100
        assert t["shares"] == 100

    def test_t_plus_0_mode(self):
        acct = Account(100_000.0, t_plus_1=False)
        acct.buy("000001", 100, 10.0, D1)
        assert acct.sell("000001", 100, 11.0, D1)["shares"] == 100


class TestSell:
    def test_sell_fee_includes_stamp_tax(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        acct.settle_new_day(D2)
        t = acct.sell("000001", 100, 11.0, D2)
        gross = 1100.0
        fee = gross * 0.0003 + gross * 0.001
        assert t["commission"] == pytest.approx(round(fee, 2))
        assert t["amount"] == pytest.approx(round(gross - fee, 2))
        assert t["pnl"] == pytest.approx(round((11 - 10) * 100 - fee, 2))
        assert t["pnl_pct"] == pytest.approx(10.0)

    def test_full_sell_removes_position(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        acct.settle_new_day(D2)
        acct.sell("000001", 100, 11.0, D2)
        assert "000001" not in acct.positions

    def test_sell_unknown_code(self, acct):
        assert acct.sell("999999", 100, 10.0, D1) is None


class TestValuation:
    def test_total_value(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        assert acct.total_value({"000001": 12.0}) == pytest.approx(acct.cash + 1200)

    def test_missing_price_falls_back_to_avg_cost(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        assert acct.position_value({}) == pytest.approx(1000.0)


class TestSerialization:
    def test_roundtrip(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        acct.settle_new_day(D2)
        acct.buy("600030", 200, 20.0, D2)
        restored = Account.from_dict(acct.to_dict())
        assert restored.cash == pytest.approx(acct.cash)
        assert restored.positions.keys() == acct.positions.keys()
        p0, p1 = restored.positions["000001"], acct.positions["000001"]
        assert (p0.total_amount, p0.closeable_amount, p0.avg_cost) == \
               (p1.total_amount, p1.closeable_amount, p1.avg_cost)
        assert restored.positions["600030"].closeable_amount == 0  # T+1 状态保留
        assert restored.positions["600030"].last_buy_date == D2


class TestContextObjects:
    def test_portfolio_view(self, acct):
        acct.buy("000001", 100, 10.0, D1)
        pf = Portfolio(acct)
        pf.update_prices({"000001": 12.0})
        assert pf.positions["000001"].value == pytest.approx(1200.0)
        assert pf.positions["000001.XSHE"].total_amount == 100  # 键宽容
        assert "000001.SZ" in pf.positions
        assert pf.total_value == pytest.approx(acct.cash + 1200)

    def test_context_user_attrs(self, acct):
        ctx = Context(Portfolio(acct))
        ctx.stock_num = 5
        assert ctx.stock_num == 5
        with pytest.raises(AttributeError):
            _ = ctx.undefined_attr

    def test_g_pickle_roundtrip(self):
        g = G()
        g.hold_list = ["000001"]
        g2 = G()
        g2.load_bytes(g.state_bytes())
        assert g2.hold_list == ["000001"]
