"""Feishu image upload and send helpers."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import requests

FEISHU_IMAGE_UPLOAD_URL = "https://open.feishu.cn/open-apis/im/v1/images"
FEISHU_MESSAGE_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


class FeishuImageError(RuntimeError):
    """Raised when uploading or sending a Feishu image fails."""


class FeishuImageClient:
    """Upload local images to Feishu and return image_key values."""

    def __init__(self, tenant_access_token: str, timeout: float = 30.0) -> None:
        if not tenant_access_token:
            raise ValueError("tenant_access_token is required")
        self.tenant_access_token = tenant_access_token
        self.timeout = timeout

    def upload_image(self, image_path: str | Path, image_type: str = "message") -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if not path.is_file():
            raise IsADirectoryError(path)

        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {"Authorization": f"Bearer {self.tenant_access_token}"}
        with path.open("rb") as fh:
            files = {"image": (path.name, fh, mime_type)}
            data = {"image_type": image_type}
            resp = requests.post(
                FEISHU_IMAGE_UPLOAD_URL,
                headers=headers,
                data=data,
                files=files,
                timeout=self.timeout,
            )
        if resp.status_code >= 400:
            raise FeishuImageError(f"Feishu upload failed: {resp.status_code} {resp.text}")
        payload: dict[str, Any] = resp.json()
        if payload.get("code", 0) != 0:
            raise FeishuImageError(f"Feishu upload error: {payload}")
        image_key = (payload.get("data") or {}).get("image_key")
        if not image_key:
            raise FeishuImageError(f"Feishu upload response missing image_key: {payload}")
        return image_key

    def send_image_message(self, image_key: str, receive_id: str, receive_id_type: str = "chat_id") -> dict[str, Any]:
        if not image_key:
            raise ValueError("image_key is required")
        if receive_id_type not in {"chat_id", "open_id", "user_id", "union_id"}:
            raise ValueError("invalid receive_id_type")
        headers = {"Authorization": f"Bearer {self.tenant_access_token}", "Content-Type": "application/json"}
        body: dict[str, Any] = {
            "receive_id": receive_id,
            "msg_type": "image",
            "content": {"image_key": image_key},
        }
        resp = requests.post(
            f"{FEISHU_MESSAGE_SEND_URL}?receive_id_type={receive_id_type}",
            headers=headers,
            json=body,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise FeishuImageError(f"Feishu send failed: {resp.status_code} {resp.text}")
        payload: dict[str, Any] = resp.json()
        if payload.get("code", 0) != 0:
            raise FeishuImageError(f"Feishu send error: {payload}")
        return payload
