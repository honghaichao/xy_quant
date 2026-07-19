"""Run a local Feishu image send demo from this repository.

Usage:
  FEISHU_TENANT_ACCESS_TOKEN=... FEISHU_RECEIVE_ID=... \
  python3 scripts/feishu_send_demo.py /path/to/image.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.feishu_image import FeishuImageClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload and send a local image to Feishu.")
    parser.add_argument("image_path", help="Local image path")
    parser.add_argument("--tenant-access-token", default=os.getenv("FEISHU_TENANT_ACCESS_TOKEN", ""), help="Feishu tenant access token")
    parser.add_argument("--receive-id", default=os.getenv("FEISHU_RECEIVE_ID", ""), help="Target chat_id/open_id/user_id/union_id")
    parser.add_argument("--receive-id-type", default=os.getenv("FEISHU_RECEIVE_ID_TYPE", "chat_id"), choices=["chat_id", "open_id", "user_id", "union_id"], help="Type of receive_id")
    parser.add_argument("--caption", default=os.getenv("FEISHU_CAPTION", ""), help="Optional caption for logs only")
    parser.add_argument("--dry-run", action="store_true", help="Only upload and print image_key")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = FeishuImageClient(args.tenant_access_token)
    image_key = client.upload_image(Path(args.image_path))
    result: dict[str, object] = {"image_key": image_key, "caption": args.caption}

    if not args.dry_run:
        if not args.receive_id:
            raise SystemExit("--receive-id is required unless --dry-run is set")
        send_result = client.send_image_message(
            image_key=image_key,
            receive_id=args.receive_id,
            receive_id_type=args.receive_id_type,
        )
        result["send_result"] = send_result

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
