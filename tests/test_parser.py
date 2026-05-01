import unittest

from mtg_price_tracker.parser import parse_card_line


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

    def test_parse_bracket_set_suffix(self):
        card = parse_card_line("Sol Ring [LTC]")

        self.assertIsNotNone(card)
        self.assertEqual(card.quantity, 1)
        self.assertEqual(card.name, "Sol Ring")
        self.assertEqual(card.set_code, "ltc")

    def test_ignore_blank_and_comment_lines(self):
        self.assertIsNone(parse_card_line(""))
        self.assertIsNone(parse_card_line("# commander deck"))


if __name__ == "__main__":
    unittest.main()
