"""报告渲染接口。"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class IReportRenderer(ABC):
    """Report renderer interface."""

    @abstractmethod
    def render(self, data: dict[str, Any], output_path: Path) -> Path:
        """Render report to output path."""
