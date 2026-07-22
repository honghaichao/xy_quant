"""
策略注册表模块

提供策略元数据管理和策略类加载功能。
支持从 STRATEGY_CONFIG 加载已有配置以保持向后兼容。

使用示例:
    from strategies.registry import Registry, StrategyMetadata
    
    # 获取注册表实例
    registry = Registry()
    
    # 列出所有策略
    print(registry.list())
    
    # 获取策略类
    strategy_class = registry.get('天宫B2策略v2')
    
    # 过滤策略
    threshold_strategies = registry.filter(threshold_required=True)
"""

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
STRATEGIES_DIR = PROJECT_ROOT / 'strategies'

# ── DuckDB helper (avoids circular imports) ──────────────────────
_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        from config.settings import settings
        _DB_PATH = Path(settings.duckdb_path)
    return _DB_PATH


def _db_connect(read_only: bool = False):
    import duckdb
    return duckdb.connect(str(_get_db_path()), read_only=read_only)


@dataclass
class StrategyMetadata:
    """
    策略元数据
    
    属性:
        name: 策略名称 (与文件名对应,不含.py)
        threshold_required: 是否需要threshold参数
        min_data_days: 最小数据天数
        description: 策略描述
        author: 作者
        version: 版本号
    """
    name: str
    threshold_required: bool = True
    min_data_days: int = 60
    description: str = ""
    author: str = ""
    version: str = "1.0.0"


def register(
    name: str,
    threshold_required: bool = True,
    min_data_days: int = 60,
    description: str = ""
):
    """
    策略注册装饰器
    
    Args:
        name: 策略名称
        threshold_required: 是否需要threshold参数
        min_data_days: 最小数据天数
        description: 策略描述
    
    Returns:
        装饰器函数
    
    使用示例:
        @register(name='我的策略', threshold_required=False)
        class MyStrategy(BaseStrategy):
            pass
    """
    def decorator(cls):
        metadata = StrategyMetadata(
            name=name,
            threshold_required=threshold_required,
            min_data_days=min_data_days,
            description=description
        )
        registry = Registry()
        registry.register(name, metadata)
        # 存储类引用
        registry._classes[name] = cls

        # Save to DuckDB strategy_registry table
        conn = _db_connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO strategy_registry
                   (id, name, display_name, class_path, description,
                    threshold_required, min_data_days, status, version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', '1.0.0')""",
                [name, name, name, f'strategies.{name}', description,
                 threshold_required, min_data_days],
            )
        finally:
            conn.close()

        return cls
    return decorator


class Registry:
    """
    策略注册表
    
    管理策略元数据和策略类的注册、查询、过滤操作。
    支持单例模式,确保全局只有一个注册表实例。
    
    使用示例:
        registry = Registry()
        registry.register('我的策略', StrategyMetadata(name='我的策略'))
        strategy_class = registry.get('我的策略')
        print(registry.list())
    """
    
    _instance: Optional['Registry'] = None
    _initialized: bool = False
    
    @classmethod
    def clear(cls) -> None:
        """清除所有注册信息 (仅用于测试)"""
        if cls._instance is not None:
            cls._instance._metadata.clear()
            cls._instance._classes.clear()
            cls._instance._modules.clear()
        cls._initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if Registry._initialized:
            return
        
        # 内部注册表: name -> StrategyMetadata
        self._metadata: dict[str, StrategyMetadata] = {}
        
        # 策略类缓存: name -> class
        self._classes: dict[str, type] = {}
        
        # 已加载的模块缓存: name -> module
        self._modules: dict[str, object] = {}
        
        # 从数据库加载策略
        self._load_from_database()
        
        Registry._initialized = True
    
    def _load_from_database(self) -> None:
        """从 DuckDB strategy_registry 表加载策略元数据."""
        try:
            conn = _db_connect(read_only=True)
            try:
                rows = conn.execute(
                    "SELECT name, threshold_required, min_data_days, description, "
                    "author, version "
                    "FROM strategy_registry WHERE status = 'active'"
                ).fetchall()
            finally:
                conn.close()

            for row in rows:
                name = row[0]
                if not name:
                    continue
                metadata = StrategyMetadata(
                    name=name,
                    threshold_required=bool(row[1]),
                    min_data_days=int(row[2] or 60),
                    description=str(row[3] or ""),
                    author=str(row[4] or ""),
                    version=str(row[5] or "1.0.0"),
                )
                self._metadata[name] = metadata

                strategy_class = self._load_strategy_class(name)
                if strategy_class is not None:
                    self._classes[name] = strategy_class

        except Exception:
            pass
    
    def register(self, name: str, metadata: StrategyMetadata) -> None:
        """
        注册策略
        
        Args:
            name: 策略名称
            metadata: 策略元数据
        """
        if not isinstance(metadata, StrategyMetadata):
            raise TypeError("metadata must be a StrategyMetadata instance")
        
        metadata.name = name  # 确保name字段一致
        self._metadata[name] = metadata
    
    def get(self, name: str) -> Optional[type]:
        """
        获取策略类
        
        Args:
            name: 策略名称 (与文件名对应,不含.py)
            
        Returns:
            策略类,如果未找到返回 None
        """
        # 检查缓存
        if name in self._classes:
            return self._classes[name]
        
        # 尝试加载策略类
        strategy_class = self._load_strategy_class(name)
        
        if strategy_class is not None:
            self._classes[name] = strategy_class
        
        return strategy_class
    
    def _load_strategy_class(self, name: str) -> Optional[type]:
        """
        动态加载策略类
        
        Args:
            name: 策略名称
            
        Returns:
            策略类,如果加载失败返回 None
        """
        strategy_file = STRATEGIES_DIR / f'{name}.py'
        
        if not strategy_file.exists():
            return None
        
        try:
            # 检查模块是否已加载
            module_name = f"strategies.{name}"
            
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                # 使用 importlib.util 从文件加载
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    strategy_file
                )
                if spec is None or spec.loader is None:
                    return None
                
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            
            self._modules[name] = module
            
            from strategies.base.framework_strategy import BaseStrategy
            from strategies.base.portfolio_strategy import PortfolioStrategy

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                    and attr_name not in ('BaseStrategy', 'FrameworkStrategy', 'PortfolioStrategy')
                    and (issubclass(attr, BaseStrategy) or issubclass(attr, PortfolioStrategy))):
                    return attr
            
            return None
            
        except Exception:
            return None
    
    def list(self, status: str = 'active') -> List[str]:
        """列出已注册策略名称（默认只返回active状态）."""
        names: list[str] = []
        conn = _db_connect(read_only=True)
        try:
            rows = conn.execute(
                "SELECT name FROM strategy_registry WHERE status = ? ORDER BY name",
                [status],
            ).fetchall()
            names = [str(row[0]) for row in rows]
        except Exception:
            pass
        finally:
            conn.close()
        return names

    def list_all(self) -> List[str]:
        """列出所有已注册策略名称（包括已废弃的策略）."""
        names: list[str] = []
        conn = _db_connect(read_only=True)
        try:
            rows = conn.execute(
                "SELECT name FROM strategy_registry ORDER BY name"
            ).fetchall()
            names = [str(row[0]) for row in rows]
        except Exception:
            pass
        finally:
            conn.close()
        return names
    
    def filter(self, **kwargs) -> List[str]:
        """
        根据条件过滤策略
        
        Args:
            **kwargs: 过滤条件,支持 threshold_required, min_data_days 等
            
        Returns:
            符合条件的策略名称列表
        """
        results = []
        
        for name, metadata in self._metadata.items():
            match = True
            
            for key, value in kwargs.items():
                if not hasattr(metadata, key):
                    match = False
                    break
                
                if getattr(metadata, key) != value:
                    match = False
                    break
            
            if match:
                results.append(name)
        
        return results
    
    def is_registered(self, name: str) -> bool:
        """
        检查策略是否已注册
        
        Args:
            name: 策略名称
            
        Returns:
            是否已注册
        """
        return name in self._metadata
    
    def get_metadata(self, name: str) -> Optional[StrategyMetadata]:
        """
        获取策略元数据
        
        Args:
            name: 策略名称
            
        Returns:
            策略元数据,如果未找到返回 None
        """
        return self._metadata.get(name)
    
    def __contains__(self, name: str) -> bool:
        """支持 'in' 操作符"""
        return self.is_registered(name)
    
    def __len__(self) -> int:
        """返回已注册策略数量"""
        return len(self._metadata)
    
    def __iter__(self):
        """支持迭代"""
        return iter(self._metadata.keys())
    
    def soft_delete(self, name: str) -> bool:
        """软删除策略 (标记为deprecated)."""
        if name not in self._metadata:
            return False

        conn = _db_connect()
        try:
            conn.execute(
                "UPDATE strategy_registry SET status = 'archived', "
                "updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                [name],
            )
        finally:
            conn.close()

        if name in self._classes:
            del self._classes[name]
        if name in self._metadata:
            del self._metadata[name]

        return True
