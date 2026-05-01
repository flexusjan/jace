from decimal import Decimal
import unittest

from mtg_price_tracker.importer import import_cards
from mtg_price_tracker.models import CardPrice, CardRequest


class FakeClient:
    def fetch_card_price(self, card, currency):
        return CardPrice(
            scryfall_id="card-1",
            name=card.name,
            set_code=card.set_code or "abc",
            collector_number=card.collector_number or "1",
            currency=currency.upper(),
            price=Decimal("1.00"),
            source_url="https://scryfall.example/card-1",
        )


class FakeBatchClient:
    def __init__(self):
        self.calls = []

    def fetch_card_prices(self, cards, currency):
        self.calls.append((cards, currency))
        return [
            (
                card,
                CardPrice(
                    scryfall_id=f"card-{index}",
                    name=card.name,
                    set_code=card.set_code or "abc",
                    collector_number=card.collector_number or "1",
                    currency=currency.upper(),
                    price=Decimal("1.00"),
                    source_url=f"https://scryfall.example/card-{index}",
                ),
                None,
            )
            for index, card in enumerate(cards, start=1)
        ]


class FakeChunkedBatchClient:
    def fetch_card_price_batches(self, cards, currency):
        return [
            [
                (
                    card,
                    CardPrice(
                        scryfall_id=f"card-{index}",
                        name=card.name,
                        set_code=card.set_code or "abc",
                        collector_number=card.collector_number or "1",
                        currency=currency.upper(),
                        price=Decimal("1.00"),
                        source_url=f"https://scryfall.example/card-{index}",
                    ),
                    None,
                )
                for index, card in enumerate(cards[:2], start=1)
            ],
            [
                (
                    cards[2],
                    CardPrice(
                        scryfall_id="card-3",
                        name=cards[2].name,
                        set_code=cards[2].set_code or "abc",
                        collector_number=cards[2].collector_number or "1",
                        currency=currency.upper(),
                        price=Decimal("1.00"),
                        source_url="https://scryfall.example/card-3",
                    ),
                    None,
                )
            ],
        ]


class FakeStore:
    def __init__(self):
        self.snapshots = []

    def save_snapshot(self, request, price):
        self.snapshots.append((request, price))


class ImporterTest(unittest.TestCase):
    def test_progress_reports_card_before_fetch_completes(self):
        updates = []
        store = FakeStore()

        result = import_cards(
            [CardRequest(quantity=1, name="Counterspell", set_code="clu", collector_number="84")],
            store,
            client=FakeClient(),
            progress=updates.append,
        )

        self.assertEqual(result.imported, 1)
        self.assertEqual(updates[0]["started"], 1)
        self.assertEqual(updates[0]["processed"], 0)
        self.assertEqual(updates[0]["current_card"], "Counterspell")
        self.assertEqual(updates[-1]["processed"], 1)

    def test_import_uses_batch_fetch_when_available(self):
        store = FakeStore()
        client = FakeBatchClient()

        result = import_cards(
            [
                CardRequest(quantity=1, name="Counterspell", set_code="clu", collector_number="84"),
                CardRequest(quantity=1, name="Sol Ring", set_code="ltc", collector_number="314"),
            ],
            store,
            client=client,
        )

        self.assertEqual(result.imported, 2)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(client.calls[0][0]), 2)
        self.assertEqual(len(store.snapshots), 2)

    def test_progress_reports_completed_bulk_batches(self):
        updates = []
        store = FakeStore()

        result = import_cards(
            [
                CardRequest(quantity=1, name="Counterspell"),
                CardRequest(quantity=1, name="Sol Ring"),
                CardRequest(quantity=1, name="Lightning Bolt"),
            ],
            store,
            client=FakeChunkedBatchClient(),
            progress=updates.append,
        )

        self.assertEqual(result.imported, 3)
        self.assertEqual([update["processed"] for update in updates], [0, 2, 2, 3])
        self.assertEqual([update["started"] for update in updates], [2, 2, 3, 3])
        self.assertEqual(len(store.snapshots), 3)


if __name__ == "__main__":
    unittest.main()
