from decimal import Decimal
import unittest
from unittest.mock import patch

from jace.exchange import ExchangeRateClient, ExchangeRateError, rate_from_payload


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


class ExchangeTest(unittest.TestCase):
    def test_convert_returns_same_amount_for_same_currency(self):
        client = ExchangeRateClient()

        self.assertEqual(client.convert(Decimal("1.23"), "EUR", "eur"), Decimal("1.23"))

    def test_convert_rejects_unsupported_currency_pair(self):
        client = ExchangeRateClient()

        with self.assertRaisesRegex(ExchangeRateError, "Cannot convert EUR to TIX"):
            client.convert(Decimal("1.23"), "eur", "tix")

    @patch("jace.exchange.urlopen")
    def test_convert_fetches_rate_rounds_and_caches_it(self, urlopen):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, timeout, request.headers["User-agent"]))
            return FakeResponse(b'{"rate": 1.234}')

        urlopen.side_effect = fake_urlopen
        client = ExchangeRateClient(base_url="https://rates.example", timeout=3)
        first = client.convert(Decimal("2.00"), "eur", "usd")
        second = client.convert(Decimal("2.00"), "eur", "usd")

        self.assertEqual(first, Decimal("2.47"))
        self.assertEqual(second, Decimal("2.47"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "https://rates.example/rate/EUR/USD")
        self.assertEqual(calls[0][1], 3)
        self.assertIn("jace", calls[0][2].casefold())

    def test_rate_from_payload_accepts_current_list_shape(self):
        payload = [
            {"base": "USD", "quote": "EUR", "rate": "0.91"},
            {"base": "EUR", "quote": "USD", "rate": "1.10"},
        ]

        self.assertEqual(rate_from_payload(payload, "EUR", "USD"), Decimal("1.10"))

    def test_rate_from_payload_rejects_missing_rate(self):
        with self.assertRaisesRegex(ExchangeRateError, "did not include EUR/USD"):
            rate_from_payload({"amount": 1}, "EUR", "USD")


if __name__ == "__main__":
    unittest.main()
