from datetime import datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch

from jace.models import CardPrice, CardRequest
from jace.refresher import (
    format_collection_stats,
    iso_or_none,
    refresh_cards,
    refresh_prices,
)
from jace.storage import CollectionStats, TrackedCard


class FakeRefreshStore:
    def __init__(self, cards=None):
        self.cards = cards or []
        self.saved = []
        self.closed = False
        self.stale_cutoffs = []
        self.tracked_called = False

    def stale_tracked_cards(self, cutoff):
        self.stale_cutoffs.append(cutoff)
        return self.cards

    def tracked_cards(self):
        self.tracked_called = True
        return self.cards

    def save_snapshot(self, request, price, entry_id=None):
        self.saved.append((request, price, entry_id))

    def close(self):
        self.closed = True


class FakeScryfall:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def fetch_card_prices_by_id(self, pairs, currency):
        self.calls.append((pairs, currency))
        return self.results[currency]


class RefresherTest(unittest.TestCase):
    def test_iso_or_none_formats_seconds_or_none(self):
        value = datetime(2026, 2, 1, 12, 30, 45, 123456, tzinfo=timezone.utc)

        self.assertEqual(iso_or_none(value), "2026-02-01T12:30:45+00:00")
        self.assertIsNone(iso_or_none(None))

    def test_format_collection_stats(self):
        self.assertEqual(
            format_collection_stats(CollectionStats(cards=2, tracked_entries=3, snapshots=4)),
            "cards=2 tracked_entries=3 snapshots=4",
        )

    @patch("jace.refresher.refresh_cards", return_value=1)
    @patch("jace.refresher.PriceStore")
    def test_refresh_prices_uses_stale_cards_and_closes_store(self, price_store, refreshed):
        tracked = tracked_card("entry-1", "card-1", "Sol Ring")
        store = FakeRefreshStore([tracked])

        def fake_price_store(database_url, initialize_schema):
            self.assertEqual(database_url, "postgres://db")
            self.assertFalse(initialize_schema)
            return store

        price_store.side_effect = fake_price_store
        count = refresh_prices("postgres://db", stale_after_seconds=60)

        self.assertEqual(count, 1)
        self.assertEqual(len(store.stale_cutoffs), 1)
        self.assertFalse(store.tracked_called)
        self.assertTrue(store.closed)
        refreshed.assert_called_once()

    @patch("jace.refresher.refresh_cards", return_value=1)
    @patch("jace.refresher.PriceStore")
    def test_refresh_prices_force_uses_all_tracked_cards(self, price_store, refresh_cards):
        store = FakeRefreshStore([tracked_card("entry-1", "card-1", "Sol Ring")])

        price_store.return_value = store
        count = refresh_prices(None, force=True)

        self.assertEqual(count, 1)
        self.assertTrue(store.tracked_called)
        self.assertEqual(store.stale_cutoffs, [])
        refresh_cards.assert_called_once()

    @patch("jace.refresher.PriceStore")
    def test_refresh_prices_reports_empty_progress(self, price_store):
        updates = []
        store = FakeRefreshStore([])

        price_store.return_value = store
        count = refresh_prices(None, progress=updates.append)

        self.assertEqual(count, 0)
        self.assertEqual(updates, [{"total": 0, "processed": 0, "refreshed": 0, "failed": 0}])
        self.assertTrue(store.closed)

    @patch("jace.refresher.ScryfallClient")
    def test_refresh_cards_saves_successes_and_reports_failures(self, scryfall_client):
        sol_ring = tracked_card("entry-1", "card-1", "Sol Ring", "eur")
        bolt = tracked_card("entry-2", "card-2", "Lightning Bolt", "eur")
        price = card_price("card-1", "Sol Ring", "EUR")
        scryfall = FakeScryfall(
            {
                "eur": [
                    (sol_ring.request, price, None),
                    (bolt.request, None, RuntimeError("not found")),
                ]
            }
        )
        store = FakeRefreshStore()
        updates = []

        scryfall_client.return_value = scryfall
        refreshed = refresh_cards(store, [sol_ring, bolt], progress=updates.append)

        self.assertEqual(refreshed, 1)
        self.assertEqual(store.saved, [(sol_ring.request, price, "entry-1")])
        self.assertEqual(updates[-1], {"total": 2, "processed": 2, "refreshed": 1, "failed": 1})

    @patch("jace.refresher.ScryfallClient")
    def test_refresh_cards_groups_requests_by_currency(self, scryfall_client):
        eur_card = tracked_card("entry-1", "card-1", "Sol Ring", "eur")
        usd_card = tracked_card("entry-2", "card-2", "Counterspell", "usd")
        scryfall = FakeScryfall(
            {
                "eur": [(eur_card.request, card_price("card-1", "Sol Ring", "EUR"), None)],
                "usd": [(usd_card.request, card_price("card-2", "Counterspell", "USD"), None)],
            }
        )
        store = FakeRefreshStore()

        scryfall_client.return_value = scryfall
        refreshed = refresh_cards(store, [eur_card, usd_card])

        self.assertEqual(refreshed, 2)
        self.assertEqual([call[1] for call in scryfall.calls], ["eur", "usd"])
        self.assertEqual([saved[2] for saved in store.saved], ["entry-1", "entry-2"])


def tracked_card(entry_id, scryfall_id, name, currency="eur"):
    return TrackedCard(
        id=entry_id,
        scryfall_id=scryfall_id,
        request=CardRequest(quantity=1, name=name, set_code="ltc", collector_number="314"),
        currency=currency,
        latest_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )


def card_price(scryfall_id, name, currency):
    return CardPrice(
        scryfall_id=scryfall_id,
        name=name,
        set_code="ltc",
        collector_number="314",
        currency=currency,
        price=Decimal("1.00"),
        source_url=f"https://scryfall.example/{scryfall_id}",
    )


if __name__ == "__main__":
    unittest.main()
