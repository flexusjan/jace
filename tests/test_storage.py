from datetime import datetime, timezone
from decimal import Decimal
import unittest

from mtg_price_tracker.models import CardPrice, CardRequest
from mtg_price_tracker.storage import PriceStore, decimal_or_none, row_to_report


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows=None):
        self.cursor_instance = FakeCursor(rows)
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class StorageTest(unittest.TestCase):
    def test_save_snapshot_uses_postgres_connection(self):
        connection = FakeConnection()
        store = PriceStore(connection=connection)
        request = CardRequest(quantity=2, name="Lightning Bolt", set_code="sld", collector_number="675")
        price = CardPrice(
            scryfall_id="card-1",
            name="Lightning Bolt",
            set_code="sld",
            collector_number="675",
            currency="EUR",
            price=Decimal("2.25"),
            source_url="https://scryfall.com/card/sld/675",
        )

        store.save_snapshot(request, price, datetime(2026, 2, 1, tzinfo=timezone.utc))
        store.close()

        statements = connection.cursor_instance.statements
        self.assertIn("CREATE TABLE IF NOT EXISTS cards", statements[0][0])
        self.assertIn("CREATE TABLE IF NOT EXISTS price_snapshots", statements[1][0])
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_price_snapshots_card_time", statements[2][0])
        self.assertIn("INSERT INTO cards", statements[3][0])
        self.assertIn("INSERT INTO price_snapshots", statements[4][0])
        self.assertEqual(statements[4][1][2], 2)
        self.assertEqual(connection.commits, 2)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)

    def test_row_to_report_converts_decimal_values(self):
        row = {
            "name": "Lightning Bolt",
            "set_code": "sld",
            "collector_number": "675",
            "source_url": "https://scryfall.com/card/sld/675",
            "quantity": 2,
            "currency": "EUR",
            "latest_price": "2.25",
            "latest_captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "first_price": "1.50",
            "first_captured_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }

        report = row_to_report(row)

        self.assertEqual(report.name, "Lightning Bolt")
        self.assertEqual(report.quantity, 2)
        self.assertEqual(report.latest_price, Decimal("2.25"))
        self.assertEqual(report.first_price, Decimal("1.50"))

    def test_decimal_or_none_handles_database_nulls(self):
        self.assertIsNone(decimal_or_none(None))
        self.assertEqual(decimal_or_none(Decimal("3.10")), Decimal("3.10"))


if __name__ == "__main__":
    unittest.main()
