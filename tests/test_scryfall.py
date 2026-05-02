import unittest
from unittest.mock import patch

from jace.models import CardRequest
from jace.scryfall import (
    ScryfallClient,
    card_image_url,
    chunks,
    collection_identifier,
    match_collection_data,
    match_collection_data_by_id,
    scryfall_card_path,
)


class ScryfallTest(unittest.TestCase):
    def test_card_image_url_uses_normal_image(self):
        self.assertEqual(
            card_image_url({"image_uris": {"small": "small.jpg", "normal": "normal.jpg"}}),
            "normal.jpg",
        )

    def test_card_image_url_uses_first_face_for_double_faced_cards(self):
        self.assertEqual(
            card_image_url({"card_faces": [{"image_uris": {"large": "front.jpg"}}]}),
            "front.jpg",
        )

    def test_scryfall_card_path_encodes_collector_number(self):
        self.assertEqual(scryfall_card_path("thb", "108★"), "/cards/thb/108%E2%98%85")

    def test_collection_identifier_prefers_set_and_collector_number(self):
        identifier = collection_identifier(CardRequest(quantity=1, name="Sol Ring", set_code="ltc", collector_number="314"))

        self.assertEqual(identifier, {"set": "ltc", "collector_number": "314"})

    def test_collection_identifier_uses_name_and_set_without_collector_number(self):
        identifier = collection_identifier(CardRequest(quantity=1, name="Sol Ring", set_code="ltc"))

        self.assertEqual(identifier, {"name": "Sol Ring", "set": "ltc"})

    def test_match_collection_data_restores_input_order(self):
        requests = [
            CardRequest(quantity=1, name="Counterspell", set_code="clu", collector_number="84"),
            CardRequest(quantity=1, name="Sol Ring", set_code="ltc", collector_number="314"),
        ]
        data = [
            {"id": "card-2", "name": "Sol Ring", "set": "ltc", "collector_number": "314"},
            {"id": "card-1", "name": "Counterspell", "set": "clu", "collector_number": "84"},
        ]

        matched = match_collection_data(requests, data)

        self.assertIsNotNone(matched)
        self.assertEqual([card["id"] for card in matched], ["card-1", "card-2"])

    def test_match_collection_data_returns_none_for_missing_cards(self):
        requests = [
            CardRequest(quantity=1, name="Counterspell", set_code="clu", collector_number="84"),
            CardRequest(quantity=1, name="Sol Ring", set_code="ltc", collector_number="314"),
        ]
        data = [{"id": "card-1", "name": "Counterspell", "set": "clu", "collector_number": "84"}]

        self.assertIsNone(match_collection_data(requests, data))

    def test_match_collection_data_by_id_restores_input_order(self):
        requests = [
            (CardRequest(quantity=1, name="Counterspell"), "card-1"),
            (CardRequest(quantity=1, name="Sol Ring"), "card-2"),
        ]
        data = [{"id": "card-2"}, {"id": "card-1"}]

        matched = match_collection_data_by_id(requests, data)

        self.assertIsNotNone(matched)
        self.assertEqual([card["id"] for card in matched], ["card-1", "card-2"])

    def test_client_uses_environment_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "JACE_SCRYFALL_BASE_URL": "https://scryfall.example",
                "JACE_SCRYFALL_BULK_SIZE": "12",
                "JACE_SCRYFALL_REQUEST_INTERVAL_SECONDS": "0.3",
                "JACE_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS": "0.9",
                "JACE_SCRYFALL_TIMEOUT_SECONDS": "7",
            },
            clear=False,
        ):
            client = ScryfallClient()

        self.assertEqual(client.base_url, "https://scryfall.example")
        self.assertEqual(client.collection_batch_size, 12)
        self.assertEqual(client.pause_seconds, 0.3)
        self.assertEqual(client.collection_pause_seconds, 0.9)
        self.assertEqual(client.timeout, 7)

    def test_chunks_uses_configured_size_from_client(self):
        client = ScryfallClient(collection_batch_size=2)

        self.assertEqual(chunks([1, 2, 3], client.collection_batch_size), [[1, 2], [3]])


if __name__ == "__main__":
    unittest.main()
