"""Integration tests in a disposable schema, never in the application's schema.

Set JACE_TEST_DATABASE_URL to a dedicated test Postgres database to run these.
"""

import os
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from jace.models import CardPrice, CardRequest
from jace.storage import PriceStore, moxfield_source_key, schema_statements


@unittest.skipUnless(
    os.environ.get("JACE_TEST_DATABASE_URL"), "test Postgres not configured"
)
class PortfolioPostgresTest(unittest.TestCase):
    def setUp(self):
        self.connection = PriceStore._connect(os.environ["JACE_TEST_DATABASE_URL"])
        self.schema = "test_portfolio_" + uuid.uuid4().hex
        self.connection.execute(f'CREATE SCHEMA "{self.schema}"')
        self.connection.execute(f'SET search_path TO "{self.schema}"')
        self.connection.commit()
        self.addCleanup(self.clean_database)
        self.store = PriceStore(connection=self.connection)

    def clean_database(self):
        self.connection.rollback()
        self.connection.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.connection.commit()
        self.connection.close()

    def price(self, amount, *, currency="EUR", card="card-1"):
        return CardPrice(
            scryfall_id=card,
            name=card,
            set_code="tst",
            collector_number="1",
            currency=currency,
            price=Decimal(amount) if amount is not None else None,
            source_url="https://scryfall.com/card/tst/1",
        )

    def request(self, quantity=1, *, card="card-1"):
        return CardRequest(
            quantity=quantity, name=card, set_code="tst", collector_number="1"
        )

    def sync(self, quantity, amount, *, card="card-1"):
        self.store.apply_moxfield_sync(
            [(self.request(quantity, card=card), self.price(amount, card=card))]
        )

    def assert_value(self, total, gain):
        latest = self.store.value_history_rows()[-1]
        self.assertEqual(latest.total_value, Decimal(total))
        self.assertEqual(latest.price_change, Decimal(gain))
        self.assertIsNotNone(latest.performance_started_at)

    def test_second_copy_only_participates_in_future_price_movements(self):
        self.sync(1, "10")
        self.assert_value("10", "0")
        self.sync(2, "15")
        self.assert_value("30", "5")
        self.sync(2, "18")
        self.assert_value("36", "11")
        self.sync(2, "18")
        self.assert_value("36", "11")
        self.sync(2, "12")
        self.assert_value("24", "-1")

    def test_reduction_and_reactivation_do_not_create_losses_or_past_gains(self):
        self.sync(2, "10")
        self.sync(1, "15")
        self.assert_value("15", "10")
        entry_id = self.store.latest_rows()[0].id
        self.store.delete_tracked_cards([entry_id])
        self.assert_value("0", "10")
        self.sync(1, "50")
        self.assert_value("50", "10")
        self.sync(1, "52")
        self.assert_value("52", "12")
        self.assertEqual(self.store.latest_rows()[0].id, entry_id)
        self.assertEqual(len(self.store.history_rows_for_entry(entry_id)), 4)

    def test_moxfield_removal_and_return_preserve_earned_price_movement(self):
        self.sync(1, "10")
        self.sync(1, "15")
        self.sync(1, "20", card="card-2")
        self.assert_value("20", "5")
        self.sync(2, "50")
        self.assert_value("100", "5")

    def test_manual_additions_and_card_archival_preserve_history(self):
        entry = self.store.save_snapshot(self.request(), self.price("10"))
        self.store.capture_portfolio_value()
        self.store.save_snapshot(self.request(), self.price("15"), entry_id=entry)
        self.store.save_snapshot(self.request(), self.price("15"))
        self.store.capture_portfolio_value()
        self.assert_value("30", "5")
        before = self.store.history_rows()
        self.store.delete_cards(["card-1"])
        self.assert_value("0", "5")
        self.assertEqual(self.store.history_rows(), before)

    def test_manual_entry_adopted_by_moxfield_retains_its_basis(self):
        entry = self.store.save_snapshot(self.request(), self.price("10"))
        self.sync(2, "15")
        self.assert_value("30", "5")
        self.assertEqual(self.store.latest_rows()[0].id, entry)

    def test_refresh_of_archived_entry_cannot_earn_price_gain(self):
        entry = self.store.save_snapshot(self.request(), self.price("10"))
        self.store.delete_tracked_cards([entry])
        self.store.save_snapshot(self.request(), self.price("15"), entry_id=entry)
        self.store.capture_portfolio_value()
        self.assert_value("0", "0")

    def test_currency_switch_and_missing_quotes_do_not_invent_gains(self):
        entry = self.store.save_snapshot(
            self.request(), self.price("10", currency="USD")
        )
        self.store.save_snapshot(self.request(), self.price("15"), entry_id=entry)
        self.store.capture_portfolio_value()
        self.assert_value("15", "0")
        self.store.save_snapshot(self.request(2), self.price(None), entry_id=entry)
        self.store.save_snapshot(self.request(2), self.price("20"), entry_id=entry)
        self.store.capture_portfolio_value()
        self.assert_value("40", "0")
        self.store.save_snapshot(self.request(2), self.price("21"), entry_id=entry)
        self.store.capture_portfolio_value()
        self.assert_value("42", "2")

    def test_missing_quote_with_unchanged_quantity_keeps_last_known_basis(self):
        entry = self.store.save_snapshot(self.request(), self.price("10"))
        self.store.save_snapshot(self.request(), self.price(None), entry_id=entry)
        self.store.save_snapshot(self.request(2), self.price("15"), entry_id=entry)
        self.store.capture_portfolio_value()
        self.assert_value("30", "5")

    def test_restart_does_not_reset_performance_or_add_history(self):
        self.sync(1, "10")
        self.sync(2, "15")
        before = self.store.value_history_rows()
        self.store = PriceStore(connection=self.connection)
        self.assertEqual(self.store.value_history_rows(), before)
        self.sync(2, "18")
        self.assert_value("36", "11")
        self.assertEqual(
            self.store.value_history_rows()[-1].performance_started_at,
            before[-1].performance_started_at,
        )

    def test_failed_price_record_rolls_back_collection_and_performance(self):
        self.sync(1, "10")
        before = self.store.history_rows()
        with (
            patch.object(
                self.store,
                "_record_price_change_with_cursor",
                side_effect=RuntimeError("test failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.sync(2, "15")
        self.assertEqual(self.store.history_rows(), before)
        self.assert_value("10", "0")
        self.sync(2, "15")
        self.assert_value("30", "5")

    def test_upgrade_preserves_existing_collection_and_snapshots(self):
        # Recreate the pre-upgrade tables, without any performance data/columns.
        self.connection.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.connection.execute(f'CREATE SCHEMA "{self.schema}"')
        for statement in schema_statements():
            if "performance" not in statement:
                self.connection.execute(statement)
        self.connection.execute("""
            INSERT INTO cards (scryfall_id, name, set_code, collector_number, source_url)
            VALUES ('card-1', 'card-1', 'tst', '1', 'https://scryfall.com/card/tst/1')
        """)
        self.connection.execute(
            """
            INSERT INTO tracked_entries (entry_id, source, source_key, active, archived_at)
            VALUES ('existing', 'moxfield', %s, TRUE, NULL),
                   ('archived', 'manual', NULL, FALSE, '2026-02-01')
            """,
            (moxfield_source_key("card-1", self.request()),),
        )
        self.connection.execute("""
            INSERT INTO collection_settings (id, mode, last_sync_at)
            VALUES (1, 'moxfield', '2026-09-01')
        """)
        for entry, quantity, price, month in [
            ("existing", 1, 10, 1),
            ("existing", 2, 15, 9),
            ("archived", 3, 5, 1),
        ]:
            self.connection.execute(
                """
                INSERT INTO price_snapshots (entry_id, scryfall_id, tracked_name, quantity, currency, price, captured_at)
                VALUES (%s, 'card-1', 'card-1', %s, 'EUR', %s, %s)
            """,
                (entry, quantity, price, datetime(2026, month, 1, tzinfo=UTC)),
            )
        self.connection.execute("""
            INSERT INTO portfolio_value_snapshots (total_value, currency, active_entries, captured_at)
            VALUES (25, 'EUR', 2, '2026-01-01'), (30, 'EUR', 1, '2026-09-01')
        """)
        self.connection.commit()
        tables = [
            "cards",
            "tracked_entries",
            "price_snapshots",
            "portfolio_value_snapshots",
            "collection_settings",
        ]
        before = {
            table: self.connection.execute(
                f"SELECT * FROM {table} ORDER BY 1"
            ).fetchall()
            for table in tables
        }

        self.store = PriceStore(connection=self.connection)
        self.store = PriceStore(connection=self.connection)

        for table in tables:
            after = self.connection.execute(
                f"SELECT * FROM {table} ORDER BY 1"
            ).fetchall()
            self.assertEqual(len(after), len(before[table]))
            self.assertEqual(
                [{key: row[key] for key in before[table][0]} for row in after],
                before[table],
            )
        self.assertTrue(
            all(point.price_change is None for point in self.store.value_history_rows())
        )
        self.sync(3, "18")
        self.assert_value("54", "6")
        self.assertEqual(self.store.latest_rows()[0].quantity, 3)
        self.assertEqual(self.store.latest_rows()[0].id, "existing")
