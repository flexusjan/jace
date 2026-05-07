from datetime import datetime, timezone
from decimal import Decimal
import unittest

from jace.models import CardPrice, CardRequest
from jace.storage import PriceStore, decimal_or_none, row_to_report


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.statements = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        if "DELETE FROM cards" in statement and parameters:
            self.rowcount = len(parameters[0])
        if "COUNT(DISTINCT" in statement and "AS deleted" in statement and parameters:
            self.rows = [{"deleted": len(parameters[0])}]
        if "COUNT(*) AS total_count" in statement and "FROM price_snapshots" in statement and "WHERE entry_id = %s" in statement:
            self.rows = [{"total_count": 3}]
        elif "WITH selected AS" in statement:
            self.rows = [
                {
                    "captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                    "price": "0.25",
                    "currency": "EUR",
                }
            ]
        elif "COUNT(*) AS total_count" in statement:
            self.rows = [{"total_count": 1, "total_value": "4.50", "currency": "EUR"}]
        if "tracked_entries" in statement and "snapshots" in statement:
            self.rows = [{"cards": 2, "tracked_entries": 3, "snapshots": 5}]

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
        self.assertTrue(any("ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_url" in statement for statement, _ in statements))
        insert_cards = next(statement for statement in statements if "INSERT INTO cards" in statement[0])
        insert_snapshots = next(statement for statement in statements if "INSERT INTO price_snapshots" in statement[0])
        self.assertIsNotNone(insert_cards)
        self.assertIsInstance(insert_snapshots[1][0], str)
        self.assertEqual(insert_snapshots[1][3], 2)
        self.assertEqual(insert_snapshots[1][4], "Near Mint")
        self.assertEqual(insert_snapshots[1][5], "English")
        self.assertEqual(insert_snapshots[1][6], "Non-Foil")
        self.assertEqual(connection.commits, 2)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)

    def test_row_to_report_converts_decimal_values(self):
        row = {
            "id": "entry-1",
            "scryfall_id": "card-1",
            "name": "Lightning Bolt",
            "set_code": "sld",
            "collector_number": "675",
            "source_url": "https://scryfall.com/card/sld/675",
            "has_cached_image": False,
            "has_image_url": True,
            "quantity": 2,
            "condition": "Near Mint",
            "language": "English",
            "finish": "Non-Foil",
            "currency": "EUR",
            "latest_price": "2.25",
            "latest_captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "first_price": "1.50",
            "first_captured_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }

        report = row_to_report(row)

        self.assertEqual(report.name, "Lightning Bolt")
        self.assertEqual(report.scryfall_id, "card-1")
        self.assertTrue(report.has_image_url)
        self.assertEqual(report.quantity, 2)
        self.assertEqual(report.condition, "Near Mint")
        self.assertEqual(report.language, "English")
        self.assertEqual(report.finish, "Non-Foil")
        self.assertEqual(report.latest_price, Decimal("2.25"))
        self.assertEqual(report.first_price, Decimal("1.50"))

    def test_decimal_or_none_handles_database_nulls(self):
        self.assertIsNone(decimal_or_none(None))
        self.assertEqual(decimal_or_none(Decimal("3.10")), Decimal("3.10"))

    def test_delete_cards_removes_snapshots_then_cards(self):
        connection = FakeConnection()
        store = PriceStore(connection=connection)

        deleted = store.delete_cards(["card-1", "card-2"])

        statements = connection.cursor_instance.statements
        self.assertIn("DELETE FROM price_snapshots", statements[-2][0])
        self.assertIn("DELETE FROM cards", statements[-1][0])
        self.assertEqual(statements[-1][1][0], ["card-1", "card-2"])
        self.assertEqual(deleted, 2)
        self.assertEqual(connection.commits, 2)

    def test_history_rows_are_keyed_by_entry_id(self):
        connection = FakeConnection(
            [
                {
                    "entry_id": "entry-1",
                    "captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                    "price": "0.25",
                    "currency": "EUR",
                },
                {
                    "entry_id": "entry-2",
                    "captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                    "price": "0.75",
                    "currency": "EUR",
                },
            ]
        )
        store = PriceStore(connection=connection)

        history = store.history_rows()

        statement = connection.cursor_instance.statements[-1][0]
        self.assertIn("ps.entry_id", statement)
        self.assertEqual(history["entry-1"][0].price, Decimal("0.25"))
        self.assertEqual(history["entry-2"][0].price, Decimal("0.75"))

    def test_history_rows_for_entry_filters_by_entry_id(self):
        connection = FakeConnection(
            [
                {
                    "captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                    "price": "0.25",
                    "currency": "EUR",
                }
            ]
        )
        store = PriceStore(connection=connection)

        history = store.history_rows_for_entry("entry-1")

        statement, parameters = connection.cursor_instance.statements[-1]
        self.assertIn("WHERE entry_id = %s", statement)
        self.assertEqual(parameters[0], "entry-1")
        self.assertEqual(history[0].price, Decimal("0.25"))

    def test_history_page_for_entry_limits_newest_snapshots_and_counts_total(self):
        connection = FakeConnection()
        store = PriceStore(connection=connection)

        page = store.history_page_for_entry("entry-1", limit=100, offset=200)

        count_statement, count_parameters = connection.cursor_instance.statements[-2]
        page_statement, page_parameters = connection.cursor_instance.statements[-1]
        self.assertIn("COUNT(*) AS total_count", count_statement)
        self.assertEqual(count_parameters[0], "entry-1")
        self.assertIn("WITH selected AS", page_statement)
        self.assertIn("ORDER BY captured_at DESC, id DESC", page_statement)
        self.assertIn("LIMIT %s OFFSET %s", page_statement)
        self.assertEqual(page_parameters, ["entry-1", 100, 200])
        self.assertEqual(page.total_count, 3)
        self.assertEqual(page.rows[0].price, Decimal("0.25"))

    def test_value_history_rows_calculates_total_values_over_time(self):
        connection = FakeConnection(
            [
                {
                    "captured_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                    "total_value": "4.50",
                    "currency": "EUR",
                }
            ]
        )
        store = PriceStore(connection=connection)

        history = store.value_history_rows()

        statement = connection.cursor_instance.statements[-1][0]
        self.assertIn("collection_start", statement)
        self.assertIn("MAX(first_captured_at)", statement)
        self.assertIn("value_points", statement)
        self.assertIn("MAX(captured_at)", statement)
        self.assertIn("start_collection", statement)
        self.assertIn("latest_collection", statement)
        self.assertIn("SUM(latest_collection.price * latest_collection.quantity)", statement)
        self.assertEqual(history[0].total_value, Decimal("4.50"))
        self.assertEqual(history[0].currency, "EUR")

    def test_latest_page_applies_limit_search_sort_and_summary(self):
        captured_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
        connection = FakeConnection(
            [
                {
                    "id": "entry-1",
                    "scryfall_id": "card-1",
                    "name": "Lightning Bolt",
                    "set_code": "sld",
                    "collector_number": "675",
                    "source_url": "https://scryfall.com/card/sld/675",
                    "has_cached_image": False,
                    "has_image_url": True,
                    "quantity": 2,
                    "condition": "Near Mint",
                    "language": "English",
                    "finish": "Non-Foil",
                    "currency": "EUR",
                    "latest_price": "2.25",
                    "latest_captured_at": captured_at,
                    "first_price": "1.50",
                    "first_captured_at": captured_at,
                    "summary_total_count": 1,
                    "summary_total_value": "4.50",
                    "summary_currency": "EUR",
                }
            ]
        )
        store = PriceStore(connection=connection)

        page = store.latest_page(limit=100, offset=200, search="bolt", sort="total_price", direction="desc")

        page_statement, page_parameters = connection.cursor_instance.statements[-1]
        self.assertIn("ILIKE %s", page_statement)
        self.assertIn("total_price_sort DESC", page_statement)
        self.assertIn("LIMIT %s OFFSET %s", page_statement)
        self.assertEqual(page_parameters[-2:], [100, 200])
        self.assertIn("COUNT(*) AS summary_total_count", page_statement)
        self.assertEqual(page.rows[0].name, "Lightning Bolt")
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.total_value, Decimal("4.50"))

    def test_collection_stats_counts_cards_entries_and_snapshots(self):
        connection = FakeConnection()
        store = PriceStore(connection=connection)

        stats = store.collection_stats()

        statement = connection.cursor_instance.statements[-1][0]
        self.assertIn("COUNT(*) FROM cards", statement)
        self.assertIn("COUNT(DISTINCT entry_id)", statement)
        self.assertIn("COUNT(*) FROM price_snapshots", statement)
        self.assertEqual(stats.cards, 2)
        self.assertEqual(stats.tracked_entries, 3)
        self.assertEqual(stats.snapshots, 5)

    def test_delete_tracked_cards_removes_only_selected_tracking_entries(self):
        connection = FakeConnection()
        store = PriceStore(connection=connection)

        deleted = store.delete_tracked_cards(["entry-1"])

        statements = connection.cursor_instance.statements
        self.assertIn("COUNT(DISTINCT", statements[-3][0])
        self.assertIn("DELETE FROM price_snapshots", statements[-2][0])
        self.assertIn("NOT EXISTS", statements[-1][0])
        self.assertEqual(statements[-2][1][0], ["entry-1"])
        self.assertEqual(deleted, 1)
        self.assertEqual(connection.commits, 2)

    def test_stale_tracked_cards_returns_latest_snapshot_requests(self):
        captured_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
        connection = FakeConnection(
            [
                {
                    "id": "entry-1",
                    "scryfall_id": "card-1",
                    "name": "Sol Ring",
                    "set_code": "ltc",
                    "collector_number": "314",
                    "tracked_name": "Sol Ring",
                    "quantity": 2,
                    "condition": "Lightly Played",
                    "language": "German",
                    "finish": "Foil",
                    "currency": "EUR",
                    "latest_captured_at": captured_at,
                }
            ]
        )
        store = PriceStore(connection=connection)

        cards = store.stale_tracked_cards(datetime(2026, 2, 2, tzinfo=timezone.utc))

        statement, parameters = connection.cursor_instance.statements[-1]
        self.assertIn("DISTINCT ON (entry_id)", statement)
        self.assertIn("latest.captured_at < %s", statement)
        self.assertEqual(parameters[0], datetime(2026, 2, 2, tzinfo=timezone.utc))
        self.assertEqual(cards[0].id, "entry-1")
        self.assertEqual(cards[0].scryfall_id, "card-1")
        self.assertEqual(cards[0].request.quantity, 2)
        self.assertEqual(cards[0].request.condition, "Lightly Played")
        self.assertEqual(cards[0].request.language, "German")
        self.assertEqual(cards[0].request.finish, "Foil")
        self.assertEqual(cards[0].currency, "eur")


if __name__ == "__main__":
    unittest.main()
