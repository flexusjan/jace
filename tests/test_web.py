from datetime import datetime, timezone
from decimal import Decimal
import unittest

from mtg_price_tracker.storage import HistoryPoint, ReportRow
from mtg_price_tracker.web import cards_payload


class WebPayloadTest(unittest.TestCase):
    def test_cards_payload_includes_change_and_history(self):
        row = ReportRow(
            name="Sol Ring",
            set_code="soc",
            collector_number="128",
            source_url="https://scryfall.com/card/soc/128",
            quantity=1,
            currency="EUR",
            latest_price=Decimal("0.72"),
            latest_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            first_price=Decimal("0.50"),
            first_captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        history = {
            "Sol Ring": [
                HistoryPoint(
                    captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    price=Decimal("0.50"),
                    currency="EUR",
                ),
                HistoryPoint(
                    captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                    price=Decimal("0.72"),
                    currency="EUR",
                ),
            ]
        }

        payload = cards_payload([row], history)

        self.assertEqual(payload["cards"][0]["name"], "Sol Ring")
        self.assertEqual(payload["cards"][0]["change"], "0.22")
        self.assertEqual(len(payload["cards"][0]["history"]), 2)


if __name__ == "__main__":
    unittest.main()
