#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any


DEFAULT_MIN_DELAY_MS = 2 * 60 * 60 * 1000
DEFAULT_MAX_DELAY_MS = 3 * 60 * 60 * 1000
DEFAULT_VHOST = "kuke_test"
DEFAULT_EXCHANGE = "kukecrms.exchange.business.delay"
DEFAULT_ROUTING_KEY = "kukecrms.key.business.customer_delay"


@dataclass(frozen=True)
class DelayedMessage:
    delay_ms: int
    body: bytes
    message_id: str


def build_payload(index: int, delay_ms: int) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    return {
        "event": "customer_delay_migration_test",
        "index": index,
        "created_at_ms": now_ms,
        "expected_fire_at_ms": now_ms + delay_ms,
        "trace_id": uuid.uuid4().hex,
        "remark": "generated-by-send_delayed_messages.py",
    }


DEFAULT_QUEUE = "kukecrms.queue.business.customer_delay"


def build_delayed_message(index: int, min_delay_ms: int, max_delay_ms: int) -> DelayedMessage:
    delay_ms = random.randint(min_delay_ms, max_delay_ms)
    payload = build_payload(index=index, delay_ms=delay_ms)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return DelayedMessage(
        delay_ms=delay_ms,
        body=body,
        message_id=payload["trace_id"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send delayed messages to a RabbitMQ x-delayed-message exchange."
    )
    parser.add_argument("--host", default="39.96.192.159", help="RabbitMQ host.")
    parser.add_argument("--port", type=int, default=276, help="RabbitMQ port. Default: 5672.")
    parser.add_argument("--username", default="default_user_I82B7eCElgZRJxwJFx8", help="RabbitMQ username.")
    parser.add_argument("--password", default="MP1iyMCJ8anlYHq8YB1-WEfkplT7WuL6", help="RabbitMQ password.")
    parser.add_argument("--vhost", default=DEFAULT_VHOST, help=f"RabbitMQ vhost. Default: {DEFAULT_VHOST}.")
    parser.add_argument(
        "--exchange",
        default=DEFAULT_EXCHANGE,
        help=f"Delayed exchange name. Default: {DEFAULT_EXCHANGE}.",
    )
    parser.add_argument(
        "--routing-key",
        default=DEFAULT_ROUTING_KEY,
        help=f"Routing key. Default: {DEFAULT_ROUTING_KEY}.",
    )
    parser.add_argument(
        "--queue",
        default=DEFAULT_QUEUE,
        help=f"Target queue name. Default: {DEFAULT_QUEUE}.",
    )
    parser.add_argument(
        "--mandatory",
        action="store_true",
        help=(
            "Publish with AMQP mandatory flag. "
            "For x-delayed-message with x-delay > 0 this is usually incorrect, "
            "because the exchange stores the message first and does not report an immediate route."
        ),
    )
    parser.add_argument("--count", type=int, default=10000, help="How many delayed messages to send. Default: 10.")
    parser.add_argument(
        "--min-delay-ms",
        type=int,
        default=DEFAULT_MIN_DELAY_MS,
        help=f"Minimum delay in milliseconds. Default: {DEFAULT_MIN_DELAY_MS}.",
    )
    parser.add_argument(
        "--max-delay-ms",
        type=int,
        default=DEFAULT_MAX_DELAY_MS,
        help=f"Maximum delay in milliseconds. Default: {DEFAULT_MAX_DELAY_MS}.",
    )
    parser.add_argument("--seed", type=int, help="Optional random seed for reproducible delays.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.count <= 0:
        raise ValueError("--count must be greater than 0")
    if args.min_delay_ms <= 0:
        raise ValueError("--min-delay-ms must be greater than 0")
    if args.max_delay_ms < args.min_delay_ms:
        raise ValueError("--max-delay-ms must be greater than or equal to --min-delay-ms")


def load_pika() -> Any:
    try:
        import pika
    except ImportError as exc:
        raise RuntimeError("missing dependency 'pika'; install it with: pip install -r requirements.txt") from exc
    return pika


def build_connection_parameters(args: argparse.Namespace, pika: Any) -> Any:
    credentials = pika.PlainCredentials(args.username, args.password)
    return pika.ConnectionParameters(
        host=args.host,
        port=args.port,
        virtual_host=args.vhost,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=30,
    )


def declare_exchange_and_binding(channel: Any, args: argparse.Namespace) -> None:
    channel.exchange_declare(
        exchange=args.exchange,
        exchange_type="x-delayed-message",
        durable=True,
        arguments={"x-delayed-type": "direct"},
    )
    channel.queue_declare(queue=args.queue, durable=True)
    channel.queue_bind(queue=args.queue, exchange=args.exchange, routing_key=args.routing_key)


def main() -> int:
    args = parse_args()
    validate_args(args)
    if args.seed is not None:
        random.seed(args.seed)

    pika = load_pika()
    params = build_connection_parameters(args, pika)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.confirm_delivery()
    declare_exchange_and_binding(channel, args)

    try:
        for index in range(1, args.count + 1):
            message = build_delayed_message(
                index=index,
                min_delay_ms=args.min_delay_ms,
                max_delay_ms=args.max_delay_ms,
            )
            properties = pika.BasicProperties(
                content_type="application/json",
                content_encoding="utf-8",
                delivery_mode=2,
                message_id=message.message_id,
                timestamp=int(time.time()),
                headers={"x-delay": message.delay_ms},
            )

            published = channel.basic_publish(
                exchange=args.exchange,
                routing_key=args.routing_key,
                body=message.body,
                properties=properties,
                mandatory=args.mandatory,
            )
            if published is False:
                raise RuntimeError(f"message {index} publish failed")

            print(
                f"[{index}/{args.count}] sent message_id={message.message_id} "
                f"delay_ms={message.delay_ms} exchange={args.exchange} routing_key={args.routing_key}"
            )
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
