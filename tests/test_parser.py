import unittest

from mtg_price_tracker.parser import parse_card_csv, parse_card_line, parse_card_text


class ParserTest(unittest.TestCase):
    def test_parse_simple_name(self):
        card = parse_card_line("Black Lotus")

        self.assertIsNotNone(card)
        self.assertEqual(card.quantity, 1)
        self.assertEqual(card.name, "Black Lotus")
        self.assertIsNone(card.set_code)
        self.assertIsNone(card.collector_number)

    def test_parse_quantity_and_arena_export(self):
        card = parse_card_line("2 Lightning Bolt (SLD) 675")

        self.assertIsNotNone(card)
        self.assertEqual(card.quantity, 2)
        self.assertEqual(card.name, "Lightning Bolt")
        self.assertEqual(card.set_code, "sld")
        self.assertEqual(card.collector_number, "675")

    def test_parse_scryfall_export_with_trailing_marker(self):
        card = parse_card_line("1 Lightning Bolt (SLD) 675 *F*")

        self.assertIsNotNone(card)
        self.assertEqual(card.quantity, 1)
        self.assertEqual(card.name, "Lightning Bolt")
        self.assertEqual(card.set_code, "sld")
        self.assertEqual(card.collector_number, "675")

    def test_parse_bracket_set_suffix(self):
        card = parse_card_line("Sol Ring [LTC]")

        self.assertIsNotNone(card)
        self.assertEqual(card.quantity, 1)
        self.assertEqual(card.name, "Sol Ring")
        self.assertEqual(card.set_code, "ltc")

    def test_ignore_blank_and_comment_lines(self):
        self.assertIsNone(parse_card_line(""))
        self.assertIsNone(parse_card_line("# commander deck"))

    def test_parse_card_text(self):
        cards = parse_card_text("Sol Ring\n2 Lightning Bolt (SLD) 675\n")

        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].name, "Sol Ring")
        self.assertEqual(cards[1].quantity, 2)

    def test_parse_moxfield_haves_csv(self):
        cards = parse_card_csv(
            '"Count","Tradelist Count","Name","Edition","Collector Number"\n'
            '"2","2","Abstruse Appropriation","mh3","177"\n'
            '"1","1","Aang, Swift Savior // Aang and La, Ocean\'s Fury","tla","204"\n'
        )

        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].quantity, 2)
        self.assertEqual(cards[0].name, "Abstruse Appropriation")
        self.assertEqual(cards[0].set_code, "mh3")
        self.assertEqual(cards[0].collector_number, "177")
        self.assertEqual(cards[0].condition, "NM")
        self.assertEqual(cards[0].language, "English")
        self.assertEqual(cards[1].name, "Aang, Swift Savior // Aang and La, Ocean's Fury")

    def test_parse_csv_condition_and_language(self):
        cards = parse_card_csv(
            '"Count","Name","Edition","Condition","Language","Collector Number"\n'
            '"1","Counterspell","clu","Lightly Played","German","84"\n'
        )

        self.assertEqual(cards[0].condition, "LP")
        self.assertEqual(cards[0].language, "German")


if __name__ == "__main__":
    unittest.main()
