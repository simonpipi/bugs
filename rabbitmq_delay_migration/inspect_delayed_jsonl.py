#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect delayed-message JSONL and decode payload_base64."
    )
    parser.add_argument("--input", required=True, help="Path to JSONL exported or converted for replay.")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of records to print. Default: 10.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print decoded payload as plain UTF-8 text without pretty JSON formatting.",
    )
    return parser.parse_args()


def decode_payload_text(payload_base64: str) -> str:
    raw = base64.b64decode(payload_base64)
    return raw.decode("utf-8")


def format_payload(decoded_text: str, raw: bool) -> str:
    if raw:
        return decoded_text
    try:
        parsed = json.loads(decoded_text)
    except json.JSONDecodeError:
        return decoded_text
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def inspect_file(path: Path, limit: int, raw: bool) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            payload_text = decode_payload_text(record["payload_base64"])
            count += 1
            print(f"--- message {count} ---")
            print(f"msg_id: {record.get('msg_id', '')}")
            print(f"vhost: {record.get('vhost', '')}")
            print(f"exchange: {record.get('exchange', '')}")
            print(f"routing_key: {record.get('routing_key', '')}")
            print(format_payload(payload_text, raw))
            if count >= limit:
                break
    return count


def main() -> int:
    args = parse_args()
    count = inspect_file(Path(args.input), args.limit, args.raw)
    print(f"Printed {count} message(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
