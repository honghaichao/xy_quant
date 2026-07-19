"""通知接口。"""
from abc import ABC, abstractmethod
from pathlib import Path


class INotifier(ABC):
    """Notifier interface."""

    @abstractmethod
    def send_text(self, title: str, content: str) -> bool:
        """Send text message."""

    @abstractmethod
    def send_file(self, title: str, content: str, file_path: Path) -> bool:
        """Send file."""

    @abstractmethod
    def send_image(self, title: str, content: str, image_path: Path) -> bool:
        """Send image."""
