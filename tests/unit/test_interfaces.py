import inspect

from interfaces.cache import ICache
from interfaces.data_source import IDataSource
from interfaces.llm_provider import ILLMProvider
from interfaces.market_store import IMarketStore
from interfaces.meta_store import IMetaStore
from interfaces.notifier import INotifier
from interfaces.quote_subscriber import IQuoteSubscriber
from interfaces.report_renderer import IReportRenderer
from interfaces.scheduler import IScheduler
from interfaces.trade_gateway import ITradeGateway

INTERFACES = [
    IDataSource,
    IMarketStore,
    IMetaStore,
    ICache,
    IScheduler,
    INotifier,
    IQuoteSubscriber,
    ITradeGateway,
    IReportRenderer,
    ILLMProvider,
]


def test_interfaces_are_abstract() -> None:
    for interface in INTERFACES:
        assert inspect.isabstract(interface)
