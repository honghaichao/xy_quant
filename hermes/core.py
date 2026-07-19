"""Compatibility layer for Hermes-style chat callbacks and gateways.

This module provides a minimal local implementation so scripts written
against `hermes.core.on_chat` and `hermes.gateway.send_image/send_text`
can run inside this repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from utils.feishu_image import FeishuImageClient

T = TypeVar("T", bound=Callable[[Any], Any])


@dataclass
class ChatMessage:
    content: str
    chat_id: str


_callbacks: list[Callable[[ChatMessage], Any]] = []


def on_chat(func: T) -> T:
    _callbacks.append(func)
    return func


def send_text(text: str, chat_id: str) -> dict[str, str]:
    return {"type": "text", "chat_id": chat_id, "content": text}


def send_image(gateway: str, chat_id: str, image_path: str, caption: str | None = None) -> dict[str, Any]:
    if gateway != "feishu":
        raise ValueError("only feishu gateway is supported")
    raise RuntimeError(
        "Feishu bot sending requires tenant access token and receive_id configured in runtime. "
        "Use utils.feishu_image.FeishuImageClient directly for real delivery."
    )
