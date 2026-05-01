import unittest

from mtg_price_tracker.moxfield import MoxfieldError, cards_from_deck, extract_deck_id


class MoxfieldTest(unittest.TestCase):
    def test_extract_deck_id_from_url(self):
        self.assertEqual(
            extract_deck_id("https://www.moxfield.com/decks/-NnmAfqku06WdUFKO3BfOw"),
            "-NnmAfqku06WdUFKO3BfOw",
        )

    def test_cards_from_current_board_shape(self):
        deck = {
            "boards": {
                "commanders": {
                    "cards": {
                        "cmd": {
                            "quantity": 1,
                            "card": {"name": "Atraxa, Praetors' Voice", "set": "2x2", "cn": "190"},
                        }
                    }
                },
                "mainboard": {
                    "cards": {
                        "main": {
                            "quantity": 2,
                            "card": {"name": "Sol Ring", "set": "ltc", "cn": "314"},
                        }
                    }
                },
            }
        }

        cards = cards_from_deck(deck)

        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].name, "Atraxa, Praetors' Voice")
        self.assertEqual(cards[1].quantity, 2)
        self.assertEqual(cards[1].set_code, "ltc")
        self.assertEqual(cards[1].collector_number, "314")
        self.assertEqual(cards[1].condition, "NM")
        self.assertEqual(cards[1].language, "English")

    def test_cards_from_legacy_board_shape(self):
        deck = {
            "mainboard": {
                "Sol Ring": {
                    "quantity": 1,
                    "card": {"name": "Sol Ring"},
                }
            }
        }

        cards = cards_from_deck(deck)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].name, "Sol Ring")

    def test_merge_keeps_different_conditions_separate(self):
        deck = {
            "mainboard": {
                "first": {
                    "quantity": 1,
                    "condition": "NM",
                    "card": {"name": "Sol Ring", "set": "ltc", "cn": "314"},
                },
                "second": {
                    "quantity": 1,
                    "condition": "LP",
                    "card": {"name": "Sol Ring", "set": "ltc", "cn": "314"},
                },
            }
        }

        cards = cards_from_deck(deck)

        self.assertEqual(len(cards), 2)
        self.assertEqual({card.condition for card in cards}, {"NM", "LP"})

    def test_invalid_quantity_raises_moxfield_error(self):
        deck = {
            "mainboard": {
                "Sol Ring": {
                    "quantity": "not-a-number",
                    "card": {"name": "Sol Ring"},
                }
            }
        }

        with self.assertRaises(MoxfieldError):
            cards_from_deck(deck)


if __name__ == "__main__":
    unittest.main()
