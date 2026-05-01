from datetime import datetime, timezone
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest

from mtg_price_tracker.models import CardPrice, CardRequest
from mtg_price_tracker.storage import PriceStore, decimal_or_none


class StorageTest(unittest.TestCase):
    def test_latest_rows_include_change_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PriceStore(Path(directory) / "prices.sqlite")
            request = CardRequest(quantity=2, name="Lightning Bolt", set_code="sld", collector_number="675")
            first = CardPrice(
                scryfall_id="card-1",
                name="Lightning Bolt",
                set_code="sld",
                collector_number="675",
                currency="EUR",
                price=Decimal("1.50"),
                source_url="https://scryfall.com/card/sld/675",
            )
            second = CardPrice(
                scryfall_id="card-1",
                name="Lightning Bolt",
                set_code="sld",
                collector_number="675",
                currency="EUR",
                price=Decimal("2.25"),
                source_url="https://scryfall.com/card/sld/675",
            )

            store.save_snapshot(request, first, datetime(2026, 1, 1, tzinfo=timezone.utc))
            store.save_snapshot(request, second, datetime(2026, 2, 1, tzinfo=timezone.utc))
            rows = store.latest_rows()
            store.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Lightning Bolt")
        self.assertEqual(rows[0]["quantity"], 2)
        self.assertEqual(decimal_or_none(rows[0]["latest_price"]), Decimal("2.25"))
        self.assertEqual(decimal_or_none(rows[0]["first_price"]), Decimal("1.50"))


if __name__ == "__main__":
    unittest.main()
