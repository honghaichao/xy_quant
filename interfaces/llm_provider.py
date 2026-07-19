"""LLM 服务接口(P1 复盘文案可选用)。"""
from abc import ABC, abstractmethod


class ILLMProvider(ABC):
    """LLM provider interface."""

    @abstractmethod
    def generate(self, prompt: str, **kwargs: object) -> str:
        """Generate text from prompt."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return whether provider is available."""
