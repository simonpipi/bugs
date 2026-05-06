import json
import unittest

from rabbitmq_delay_migration.convert_delayed_tsv import convert_line


class ConvertDelayedTsvTest(unittest.TestCase):
    def test_convert_line(self) -> None:
        raw = (
            "1776757132325\tkuke_test\tkukecrms.exchange.business.delay\t"
            "kukecrms.key.business.customer_delay\t7253198\t"
            "fde5ef5dac7848599b46e87b40964174\t1776749878\t"
            "eyJ0ZXN0Ijp0cnVlfQ==\n"
        )
        record = convert_line(raw)
        assert record is not None
        self.assertEqual(record["vhost"], "kuke_test")
        self.assertEqual(record["due_at_ms"], 1776757132325)
        self.assertEqual(record["headers"]["x-delay"]["value"], 7253198)
        self.assertEqual(record["properties"]["message_id"], "fde5ef5dac7848599b46e87b40964174")
        self.assertEqual(record["properties"]["timestamp"], 1776749878)
        self.assertEqual(record["payload_base64"], "eyJ0ZXN0Ijp0cnVlfQ==")

    def test_convert_line_skips_ok(self) -> None:
        self.assertIsNone(convert_line("ok\n"))

    def test_convert_line_full_tsv(self) -> None:
        raw = (
            "1776757132325\tkuke_test\tkukecrms.exchange.business.delay\t"
            "kukecrms.key.business.customer_delay\t"
            "fde5ef5dac7848599b46e87b40964174\t1776749878\t"
            "eyJ0ZXN0Ijp0cnVlfQ==\tSEVBREVSUw==\tUFJPUFM=\n"
        )
        record = convert_line(raw)
        assert record is not None
        self.assertEqual(record["vhost"], "kuke_test")
        self.assertEqual(record["due_at_ms"], 1776757132325)
        self.assertEqual(record["headers"]["__erlang_term_base64__"], "SEVBREVSUw==")
        self.assertEqual(record["properties"]["__erlang_term_base64__"], "UFJPUFM=")
        self.assertEqual(record["properties"]["message_id"], "fde5ef5dac7848599b46e87b40964174")
        self.assertEqual(record["properties"]["timestamp"], 1776749878)


if __name__ == "__main__":
    unittest.main()
