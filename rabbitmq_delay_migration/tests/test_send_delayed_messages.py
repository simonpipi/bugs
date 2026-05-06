import json
import unittest

from rabbitmq_delay_migration.send_delayed_messages import (
    DEFAULT_MAX_DELAY_MS,
    DEFAULT_MIN_DELAY_MS,
    build_delayed_message,
)


class SendDelayedMessagesTest(unittest.TestCase):
    def test_build_delayed_message_uses_requested_range(self) -> None:
        message = build_delayed_message(
            index=1,
            min_delay_ms=DEFAULT_MIN_DELAY_MS,
            max_delay_ms=DEFAULT_MAX_DELAY_MS,
        )
        self.assertGreaterEqual(message.delay_ms, DEFAULT_MIN_DELAY_MS)
        self.assertLessEqual(message.delay_ms, DEFAULT_MAX_DELAY_MS)

        payload = json.loads(message.body.decode("utf-8"))
        self.assertEqual(payload["index"], 1)
        self.assertEqual(payload["expected_fire_at_ms"], payload["created_at_ms"] + message.delay_ms)
        self.assertEqual(payload["trace_id"], message.message_id)


if __name__ == "__main__":
    unittest.main()
