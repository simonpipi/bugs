#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert rabbitmqctl-eval delayed-message TSV output into replay_delayed.py JSONL format."
    )
    parser.add_argument("--input", required=True, help="Input TSV file exported from rabbitmqctl eval.")
    parser.add_argument("--output", required=True, help="Output JSONL path.")
    return parser.parse_args()


def build_msg_id(
    vhost: str,
    exchange: str,
    routing_key: str,
    due_at_ms: int,
    headers: dict[str, Any],
    properties: dict[str, Any],
    payload_base64: str,
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "vhost": vhost,
                "exchange": exchange,
                "routing_key": routing_key,
                "due_at_ms": due_at_ms,
                "headers": headers,
                "properties": properties,
                "payload_base64": payload_base64,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return digest


def convert_line(raw: str) -> dict[str, Any] | None:
    line = raw.rstrip("\n")
    if not line or line == "ok":
        return None

    parts = line.split("\t")
    if len(parts) == 8:
        due_at_ms, vhost, exchange, routing_key, x_delay, message_id, timestamp, payload_base64 = parts

        headers: dict[str, Any] = {
            "x-delay": {
                "amqp_type": "signedint",
                "value": int(x_delay),
            }
        }
        properties: dict[str, Any] = {
            "content_type": "application/json",
            "content_encoding": "utf-8",
            "delivery_mode": 2,
        }
        if message_id:
            properties["message_id"] = message_id
        if timestamp and timestamp != "undefined":
            properties["timestamp"] = int(timestamp)
    elif len(parts) == 9:
        due_at_ms, vhost, exchange, routing_key, message_id, timestamp, payload_base64, headers_term_base64, properties_term_base64 = parts

        headers = {
            "__erlang_term_base64__": headers_term_base64,
        }
        properties = {
            "__erlang_term_base64__": properties_term_base64,
        }
        if message_id:
            properties["message_id"] = message_id
        if timestamp and timestamp != "undefined":
            properties["timestamp"] = int(timestamp)
    else:
        raise ValueError(f"expected 8 or 9 columns, got {len(parts)}: {line}")

    export_record = {
        "msg_id": build_msg_id(
            vhost=vhost,
            exchange=exchange,
            routing_key=routing_key,
            due_at_ms=int(due_at_ms),
            headers=headers,
            properties=properties,
            payload_base64=payload_base64,
        ),
        "vhost": vhost,
        "exchange": exchange,
        "routing_key": routing_key,
        "due_at_ms": int(due_at_ms),
        "headers": headers,
        "properties": properties,
        "payload_base64": payload_base64,
    }
    return export_record


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    count = 0
    with input_path.open("r", encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for raw in src:
            record = convert_line(raw)
            if record is None:
                continue
            dst.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            dst.write("\n")
            count += 1

    print(f"Converted {count} delayed messages to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
