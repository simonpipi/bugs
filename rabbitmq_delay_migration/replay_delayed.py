#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator
from urllib.parse import quote, urlsplit, urlunsplit


DEFAULT_SKEW_GUARD_MS = 2000
ERLANG_TERM_PLACEHOLDER = "__erlang_term_base64__"


@dataclass(frozen=True)
class ExportedMessage:
    msg_id: str
    vhost: str
    exchange: str
    routing_key: str
    due_at_ms: int
    headers: Dict[str, Any]
    properties: Dict[str, Any]
    payload_base64: str


class ReplayError(RuntimeError):
    pass


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_checkpoint (
                msg_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                published_at_ms INTEGER,
                confirm_at_ms INTEGER,
                error TEXT
            )
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def is_confirmed(self, msg_id: str) -> bool:
        row = self.conn.execute(
            "SELECT status FROM replay_checkpoint WHERE msg_id = ?",
            (msg_id,),
        ).fetchone()
        return bool(row and row[0] == "confirmed")

    def mark_confirmed(self, msg_id: str, published_at_ms: int, confirm_at_ms: int) -> None:
        self.conn.execute(
            """
            INSERT INTO replay_checkpoint (msg_id, status, published_at_ms, confirm_at_ms, error)
            VALUES (?, 'confirmed', ?, ?, NULL)
            ON CONFLICT(msg_id) DO UPDATE SET
                status = excluded.status,
                published_at_ms = excluded.published_at_ms,
                confirm_at_ms = excluded.confirm_at_ms,
                error = excluded.error
            """,
            (msg_id, published_at_ms, confirm_at_ms),
        )
        self.conn.commit()

    def mark_failed(self, msg_id: str, error: str) -> None:
        self.conn.execute(
            """
            INSERT INTO replay_checkpoint (msg_id, status, published_at_ms, confirm_at_ms, error)
            VALUES (?, 'failed', NULL, NULL, ?)
            ON CONFLICT(msg_id) DO UPDATE SET
                status = excluded.status,
                published_at_ms = NULL,
                confirm_at_ms = NULL,
                error = excluded.error
            """,
            (msg_id, error),
        )
        self.conn.commit()


class PikaPublisher:
    def __init__(self, amqp_url: str, mandatory: bool = False) -> None:
        try:
            import pika
        except ImportError as exc:
            raise ReplayError(
                "missing dependency 'pika'; install it with: pip install -r requirements.txt"
            ) from exc

        self.pika = pika
        self.mandatory = mandatory
        self.connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        self.channel = self.connection.channel()
        self.channel.confirm_delivery()

    def publish(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        properties: Any,
    ) -> None:
        try:
            published = self.channel.basic_publish(
                exchange=exchange,
                routing_key=routing_key,
                body=body,
                properties=properties,
                mandatory=self.mandatory,
            )
        except Exception as exc:  # pragma: no cover
            raise ReplayError(str(exc)) from exc

        if published is False:
            raise ReplayError("basic_publish returned False")

    def close(self) -> None:
        try:
            if self.connection.is_open:
                self.connection.close()
        except Exception:
            pass


class PublisherPool:
    def __init__(self, base_amqp_url: str, mandatory: bool = False) -> None:
        self.base_amqp_url = base_amqp_url
        self.mandatory = mandatory
        self.publishers: Dict[str, PikaPublisher] = {}

    def get(self, vhost: str) -> PikaPublisher:
        if vhost not in self.publishers:
            self.publishers[vhost] = PikaPublisher(
                replace_vhost(self.base_amqp_url, vhost),
                mandatory=self.mandatory,
            )
        return self.publishers[vhost]

    def close(self) -> None:
        for publisher in self.publishers.values():
            publisher.close()


def replace_vhost(amqp_url: str, vhost: str) -> str:
    parsed = urlsplit(amqp_url)
    encoded_vhost = quote(vhost, safe="")
    path = f"/{encoded_vhost}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def iter_messages(path: Path, vhost_filter: str) -> Iterator[ExportedMessage]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            data = json.loads(raw)
            message = ExportedMessage(
                msg_id=data["msg_id"],
                vhost=data["vhost"],
                exchange=data["exchange"],
                routing_key=data["routing_key"],
                due_at_ms=int(data["due_at_ms"]),
                headers=data.get("headers", {}),
                properties=data.get("properties", {}),
                payload_base64=data["payload_base64"],
            )
            if vhost_filter != "all" and message.vhost != vhost_filter:
                continue
            validate_message(message, line_number)
            yield message


def validate_message(message: ExportedMessage, line_number: int) -> None:
    missing = [name for name in ("msg_id", "vhost", "payload_base64") if not getattr(message, name)]
    if missing:
        raise ReplayError(f"line {line_number}: missing required fields: {', '.join(missing)}")


def decode_binary_blob(value: Dict[str, Any]) -> bytes:
    return base64.b64decode(value["data"])


def decode_scalar(value: Any) -> Any:
    if isinstance(value, dict) and value.get("encoding") == "base64":
        return decode_binary_blob(value)
    if isinstance(value, dict):
        return {k: decode_scalar(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_scalar(item) for item in value]
    return value


class ErlangETFDecoder:
    VERSION_MAGIC = 131
    SMALL_INTEGER_EXT = 97
    INTEGER_EXT = 98
    SMALL_TUPLE_EXT = 104
    LARGE_TUPLE_EXT = 105
    NIL_EXT = 106
    STRING_EXT = 107
    LIST_EXT = 108
    BINARY_EXT = 109
    SMALL_BIG_EXT = 110
    LARGE_BIG_EXT = 111
    ATOM_EXT = 100
    SMALL_ATOM_EXT = 115
    ATOM_UTF8_EXT = 118
    SMALL_ATOM_UTF8_EXT = 119

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0

    def decode(self) -> Any:
        version = self._read_byte()
        if version != self.VERSION_MAGIC:
            raise ReplayError(f"unsupported ETF version byte: {version}")
        value = self._decode_term()
        if self.offset != len(self.payload):
            raise ReplayError("unexpected trailing bytes after ETF payload")
        return value

    def _read(self, size: int) -> bytes:
        chunk = self.payload[self.offset : self.offset + size]
        if len(chunk) != size:
            raise ReplayError("unexpected end of ETF payload")
        self.offset += size
        return chunk

    def _read_byte(self) -> int:
        return self._read(1)[0]

    def _read_u16(self) -> int:
        return int.from_bytes(self._read(2), "big", signed=False)

    def _read_u32(self) -> int:
        return int.from_bytes(self._read(4), "big", signed=False)

    def _read_i32(self) -> int:
        return int.from_bytes(self._read(4), "big", signed=True)

    def _decode_atom_text(self, data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")

    def _decode_term(self) -> Any:
        tag = self._read_byte()

        if tag == self.SMALL_INTEGER_EXT:
            return self._read_byte()
        if tag == self.INTEGER_EXT:
            return self._read_i32()
        if tag == self.SMALL_BIG_EXT:
            return self._decode_big_int(self._read_byte())
        if tag == self.LARGE_BIG_EXT:
            return self._decode_big_int(self._read_u32())
        if tag == self.SMALL_TUPLE_EXT:
            arity = self._read_byte()
            return tuple(self._decode_term() for _ in range(arity))
        if tag == self.LARGE_TUPLE_EXT:
            arity = self._read_u32()
            return tuple(self._decode_term() for _ in range(arity))
        if tag == self.NIL_EXT:
            return []
        if tag == self.STRING_EXT:
            return self._read(self._read_u16())
        if tag == self.LIST_EXT:
            length = self._read_u32()
            items = [self._decode_term() for _ in range(length)]
            tail = self._decode_term()
            if tail != []:
                raise ReplayError("unsupported improper list in ETF payload")
            return items
        if tag == self.BINARY_EXT:
            return self._read(self._read_u32())
        if tag == self.ATOM_EXT:
            return self._decode_atom_text(self._read(self._read_u16()))
        if tag == self.SMALL_ATOM_EXT:
            return self._decode_atom_text(self._read(self._read_byte()))
        if tag == self.ATOM_UTF8_EXT:
            return self._decode_atom_text(self._read(self._read_u16()))
        if tag == self.SMALL_ATOM_UTF8_EXT:
            return self._decode_atom_text(self._read(self._read_byte()))

        raise ReplayError(f"unsupported ETF tag: {tag}")

    def _decode_big_int(self, digits_count: int) -> int:
        sign = self._read_byte()
        digits = self._read(digits_count)
        value = 0
        for index, byte in enumerate(digits):
            value += byte << (8 * index)
        if sign == 1:
            value = -value
        return value


def decode_erlang_term_base64(encoded: str) -> Any:
    decoder = ErlangETFDecoder(base64.b64decode(encoded))
    return decoder.decode()


def maybe_decode_binary_text(value: bytes) -> Any:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value


def decode_erlang_atom(value: Any) -> Any:
    if value == "undefined":
        return None
    return value


def decode_erlang_amqp_value(amqp_type: Any, value: Any) -> Any:
    amqp_type = decode_erlang_atom(amqp_type)
    value = decode_erlang_term_value(value)

    if amqp_type in {"longstr", "shortstr"} and isinstance(value, bytes):
        return maybe_decode_binary_text(value)
    if amqp_type == "bytearray" and isinstance(value, bytes):
        return value
    if amqp_type == "table" and isinstance(value, list):
        return erlang_headers_to_python(value)
    if amqp_type == "array" and isinstance(value, list):
        return [decode_erlang_amqp_array_item(item) for item in value]
    if amqp_type == "decimal" and isinstance(value, tuple) and len(value) == 2:
        scale, number = value
        return Decimal(number) / (Decimal(10) ** int(scale))
    return value


def decode_erlang_amqp_array_item(item: Any) -> Any:
    if isinstance(item, tuple) and len(item) == 2:
        return decode_erlang_amqp_value(item[0], item[1])
    return decode_erlang_term_value(item)


def decode_erlang_term_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value
    if isinstance(value, list):
        return [decode_erlang_term_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(decode_erlang_term_value(item) for item in value)
    if isinstance(value, str):
        return decode_erlang_atom(value)
    return value


def erlang_headers_to_python(headers_term: Any) -> Dict[str, Any]:
    if headers_term in (None, []):
        return {}
    if not isinstance(headers_term, list):
        raise ReplayError("decoded Erlang headers term is not a list")

    decoded: Dict[str, Any] = {}
    for item in headers_term:
        if not isinstance(item, tuple) or len(item) != 3:
            raise ReplayError(f"unsupported Erlang header entry: {item!r}")
        key_raw, amqp_type, value = item
        if isinstance(key_raw, bytes):
            key = maybe_decode_binary_text(key_raw)
        else:
            key = str(key_raw)
        decoded[str(key)] = decode_erlang_amqp_value(amqp_type, value)
    return decoded


def erlang_properties_to_python(properties_term: Any) -> Dict[str, Any]:
    if not isinstance(properties_term, tuple) or len(properties_term) != 15:
        raise ReplayError("decoded Erlang properties term is not a P_basic tuple")
    if properties_term[0] != "P_basic":
        raise ReplayError(f"unsupported Erlang properties tuple tag: {properties_term[0]!r}")

    (
        _tag,
        content_type,
        content_encoding,
        _headers,
        delivery_mode,
        priority,
        correlation_id,
        reply_to,
        expiration,
        message_id,
        timestamp,
        msg_type,
        user_id,
        app_id,
        cluster_id,
    ) = properties_term

    raw_props = {
        "content_type": maybe_decode_binary_text(content_type) if isinstance(content_type, bytes) else content_type,
        "content_encoding": maybe_decode_binary_text(content_encoding) if isinstance(content_encoding, bytes) else content_encoding,
        "delivery_mode": decode_erlang_atom(delivery_mode),
        "priority": decode_erlang_atom(priority),
        "correlation_id": maybe_decode_binary_text(correlation_id) if isinstance(correlation_id, bytes) else decode_erlang_atom(correlation_id),
        "reply_to": maybe_decode_binary_text(reply_to) if isinstance(reply_to, bytes) else decode_erlang_atom(reply_to),
        "expiration": maybe_decode_binary_text(expiration) if isinstance(expiration, bytes) else decode_erlang_atom(expiration),
        "message_id": maybe_decode_binary_text(message_id) if isinstance(message_id, bytes) else decode_erlang_atom(message_id),
        "timestamp": decode_erlang_atom(timestamp),
        "type": maybe_decode_binary_text(msg_type) if isinstance(msg_type, bytes) else decode_erlang_atom(msg_type),
        "user_id": maybe_decode_binary_text(user_id) if isinstance(user_id, bytes) else decode_erlang_atom(user_id),
        "app_id": maybe_decode_binary_text(app_id) if isinstance(app_id, bytes) else decode_erlang_atom(app_id),
        "cluster_id": maybe_decode_binary_text(cluster_id) if isinstance(cluster_id, bytes) else decode_erlang_atom(cluster_id),
    }

    return {key: value for key, value in raw_props.items() if value is not None}


def decode_typed_amqp_value(node: Dict[str, Any]) -> Any:
    if not isinstance(node, dict) or "amqp_type" not in node:
        return decode_scalar(node)

    amqp_type = node["amqp_type"]
    value = node.get("value")

    if amqp_type in {"longstr", "shortstr"}:
        return decode_scalar(value)
    if amqp_type == "bytearray":
        return decode_scalar(value)
    if amqp_type == "table":
        return decode_headers(value)
    if amqp_type == "array":
        return [decode_typed_amqp_value(item) for item in value]
    if amqp_type == "decimal":
        scale = int(value["scale"])
        raw = Decimal(value["value"])
        return raw / (Decimal(10) ** scale)
    if amqp_type == "void":
        return None
    if amqp_type == "timestamp":
        return int(value)
    if amqp_type in {
        "byte",
        "short",
        "signedint",
        "long",
        "unsignedbyte",
        "unsignedshort",
        "unsignedint",
        "bool",
        "float",
        "double",
    }:
        return value
    return decode_scalar(value)


def decode_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    if ERLANG_TERM_PLACEHOLDER in headers:
        return erlang_headers_to_python(decode_erlang_term_base64(headers[ERLANG_TERM_PLACEHOLDER]))
    decoded: Dict[str, Any] = {}
    for key, value in headers.items():
        if not isinstance(value, dict) or "amqp_type" not in value:
            raise ReplayError(f"header '{key}' does not contain an amqp_type marker")
        decoded[key] = decode_typed_amqp_value(value)
    return decoded


def decode_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
    if ERLANG_TERM_PLACEHOLDER in properties:
        decoded = erlang_properties_to_python(
            decode_erlang_term_base64(properties[ERLANG_TERM_PLACEHOLDER])
        )
        for passthrough in ("message_id", "timestamp"):
            if passthrough in properties and passthrough not in decoded:
                decoded[passthrough] = properties[passthrough]
        return decoded
    return {key: decode_scalar(value) for key, value in properties.items()}


def decode_payload(payload_base64: str) -> bytes:
    return base64.b64decode(payload_base64)


def build_publish_properties(message: ExportedMessage, remaining_delay_ms: int) -> Any:
    try:
        import pika
    except ImportError as exc:  # pragma: no cover
        raise ReplayError(
            "missing dependency 'pika'; install it with: pip install -r requirements.txt"
        ) from exc

    headers = decode_headers(message.headers)
    headers["x-delay"] = remaining_delay_ms
    props = decode_properties(message.properties)
    props["headers"] = headers
    return pika.BasicProperties(**props)


def compute_remaining_delay_ms(due_at_ms: int, now_ms: int, skew_guard_ms: int) -> int:
    return max(0, int(due_at_ms) - int(now_ms) - int(skew_guard_ms))


def replay_messages(
    input_path: Path,
    amqp_url: str,
    checkpoint_path: Path,
    vhost_filter: str,
    skew_guard_ms: int,
    mandatory: bool,
) -> tuple[int, int]:
    checkpoint = CheckpointStore(checkpoint_path)
    publishers = PublisherPool(amqp_url, mandatory=mandatory)
    published = 0
    skipped = 0

    try:
        for message in iter_messages(input_path, vhost_filter):
            if checkpoint.is_confirmed(message.msg_id):
                skipped += 1
                continue

            body = decode_payload(message.payload_base64)
            now_ms = current_time_ms()
            remaining_delay_ms = compute_remaining_delay_ms(
                message.due_at_ms, now_ms, skew_guard_ms
            )
            props = build_publish_properties(message, remaining_delay_ms)
            publisher = publishers.get(message.vhost)
            published_at_ms = current_time_ms()
            try:
                publisher.publish(
                    exchange=message.exchange,
                    routing_key=message.routing_key,
                    body=body,
                    properties=props,
                )
            except Exception as exc:
                checkpoint.mark_failed(message.msg_id, str(exc))
                raise ReplayError(
                    f"failed to publish msg_id={message.msg_id}: {exc}"
                ) from exc

            confirm_at_ms = current_time_ms()
            checkpoint.mark_confirmed(message.msg_id, published_at_ms, confirm_at_ms)
            published += 1
    finally:
        publishers.close()
        checkpoint.close()

    return published, skipped


def current_time_ms() -> int:
    return time.time_ns() // 1_000_000


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay RabbitMQ delayed messages exported from x-delayed-message storage."
    )
    parser.add_argument("--input", required=True, help="Path to exported JSONL file.")
    parser.add_argument("--amqp-url", required=True, help="AMQP URL for the target RabbitMQ.")
    parser.add_argument(
        "--checkpoint",
        required=True,
        help="SQLite checkpoint path used for resume and dedupe.",
    )
    parser.add_argument(
        "--vhost",
        default="all",
        help="Replay only one vhost or use 'all' to replay every record in the file.",
    )
    parser.add_argument(
        "--skew-guard-ms",
        type=int,
        default=DEFAULT_SKEW_GUARD_MS,
        help=f"Subtract this guard window when rebuilding x-delay. Default: {DEFAULT_SKEW_GUARD_MS}.",
    )
    parser.add_argument(
        "--mandatory",
        action="store_true",
        help=(
            "Publish with AMQP mandatory flag. "
            "For x-delayed-message with x-delay > 0 this is usually incorrect, "
            "so the default is disabled."
        ),
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    try:
        published, skipped = replay_messages(
            input_path=Path(args.input),
            amqp_url=args.amqp_url,
            checkpoint_path=Path(args.checkpoint),
            vhost_filter=args.vhost,
            skew_guard_ms=args.skew_guard_ms,
            mandatory=args.mandatory,
        )
    except ReplayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Published {published} messages. Skipped {skipped} already confirmed messages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
