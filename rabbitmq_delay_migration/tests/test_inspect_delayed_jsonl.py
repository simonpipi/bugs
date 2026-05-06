import base64
import json
import unittest

from rabbitmq_delay_migration.inspect_delayed_jsonl import decode_payload_text, format_payload


class InspectDelayedJsonlTest(unittest.TestCase):
    def test_decode_payload_text(self) -> None:
        encoded = base64.b64encode(b'{"hello":"world"}').decode("utf-8")
        self.assertEqual(decode_payload_text(encoded), '{"hello":"world"}')

    def test_format_payload_pretty_json(self) -> None:
        formatted = format_payload('{"hello":"world"}', raw=False)
        parsed = json.loads(formatted)
        self.assertEqual(parsed["hello"], "world")

    def test_format_payload_raw(self) -> None:
        self.assertEqual(format_payload('{"hello":"world"}', raw=True), '{"hello":"world"}')


if __name__ == "__main__":
    unittest.main()
