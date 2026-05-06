import tempfile
import unittest
from pathlib import Path

from rabbitmq_delay_migration.replay_delayed import (
    CheckpointStore,
    compute_remaining_delay_ms,
    decode_headers,
    decode_properties,
    replace_vhost,
)

HEADERS_TERM_BASE64 = "g2wAAAABaANtAAAAB3gtZGVsYXlkAAlzaWduZWRpbnRiAG6szmo="
PROPERTIES_TERM_BASE64 = (
    "g2gPZAAHUF9iYXNpY20AAAAQYXBwbGljYXRpb24vanNvbm0AAAAFdXRmLThsAAAAAWgDbQAAAAd4LWRlbGF5"
    "ZAAJc2lnbmVkaW50YgBurM5qYQJkAAl1bmRlZmluZWRkAAl1bmRlZmluZWRkAAl1bmRlZmluZWRkAAl1bmRl"
    "ZmluZWRtAAAAIGZkZTVlZjVkYWM3ODQ4NTk5YjQ2ZTg3YjQwOTY0MTc0YmnnDTZkAAl1bmRlZmluZWRkAAl1"
    "bmRlZmluZWRkAAl1bmRlZmluZWRkAAl1bmRlZmluZWQ="
)


class ReplayHelpersTest(unittest.TestCase):
    def test_replace_vhost_root(self) -> None:
        self.assertEqual(
            replace_vhost("amqp://guest:guest@localhost:5672/%2F", "/"),
            "amqp://guest:guest@localhost:5672/%2F",
        )

    def test_replace_vhost_named(self) -> None:
        self.assertEqual(
            replace_vhost("amqp://guest:guest@localhost:5672/%2F", "billing"),
            "amqp://guest:guest@localhost:5672/billing",
        )

    def test_compute_remaining_delay(self) -> None:
        self.assertEqual(compute_remaining_delay_ms(10000, 7000, 2000), 1000)
        self.assertEqual(compute_remaining_delay_ms(10000, 9500, 2000), 0)

    def test_decode_headers(self) -> None:
        headers = {
            "trace_id": {"amqp_type": "longstr", "value": "abc"},
            "retry": {"amqp_type": "signedint", "value": 3},
            "blob": {
                "amqp_type": "bytearray",
                "value": {"encoding": "base64", "data": "AQI="},
            },
            "nested": {
                "amqp_type": "table",
                "value": {
                    "child": {"amqp_type": "bool", "value": True},
                },
            },
        }
        decoded = decode_headers(headers)
        self.assertEqual(decoded["trace_id"], "abc")
        self.assertEqual(decoded["retry"], 3)
        self.assertEqual(decoded["blob"], b"\x01\x02")
        self.assertEqual(decoded["nested"]["child"], True)

    def test_decode_headers_erlang_term_placeholder(self) -> None:
        headers = {"__erlang_term_base64__": HEADERS_TERM_BASE64}
        decoded = decode_headers(headers)
        self.assertEqual(decoded["x-delay"], 7253198)

    def test_decode_properties_erlang_term_placeholder(self) -> None:
        properties = {
            "__erlang_term_base64__": PROPERTIES_TERM_BASE64,
            "message_id": "fde5ef5dac7848599b46e87b40964174",
            "timestamp": 1776749878,
        }
        decoded = decode_properties(properties)
        self.assertEqual(decoded["content_type"], "application/json")
        self.assertEqual(decoded["content_encoding"], "utf-8")
        self.assertEqual(decoded["delivery_mode"], 2)
        self.assertEqual(decoded["message_id"], "fde5ef5dac7848599b46e87b40964174")
        self.assertEqual(decoded["timestamp"], 1776749878)


class CheckpointStoreTest(unittest.TestCase):
    def test_mark_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = CheckpointStore(Path(tmpdir) / "checkpoint.sqlite3")
            self.assertFalse(checkpoint.is_confirmed("m1"))
            checkpoint.mark_confirmed("m1", 1, 2)
            self.assertTrue(checkpoint.is_confirmed("m1"))
            checkpoint.close()


if __name__ == "__main__":
    unittest.main()
