import unittest
from unittest.mock import patch

from jace.config import app_config


class ConfigTest(unittest.TestCase):
    def test_app_config_uses_environment_values(self):
        with patch.dict(
            "os.environ",
            {
                "JACE_DEFAULT_CURRENCY": "usd",
                "JACE_WEB_HOST": "127.0.0.1",
                "JACE_WEB_PORT": "9000",
                "JACE_REFRESH_INTERVAL_SECONDS": "120",
                "JACE_SCRYFALL_BULK_SIZE": "10",
                "JACE_SCRYFALL_REQUEST_INTERVAL_SECONDS": "0.2",
                "JACE_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS": "0.8",
                "JACE_SCRYFALL_TIMEOUT_SECONDS": "5",
                "JACE_IMAGE_FETCH_TIMEOUT_SECONDS": "6",
            },
            clear=False,
        ):
            config = app_config()

        self.assertEqual(config.default_currency, "usd")
        self.assertEqual(config.web_host, "127.0.0.1")
        self.assertEqual(config.web_port, 9000)
        self.assertEqual(config.refresh_interval_seconds, 120)
        self.assertEqual(config.scryfall_bulk_size, 10)
        self.assertEqual(config.scryfall_request_interval_seconds, 0.2)
        self.assertEqual(config.scryfall_collection_request_interval_seconds, 0.8)
        self.assertEqual(config.scryfall_timeout_seconds, 5)
        self.assertEqual(config.image_fetch_timeout_seconds, 6)

    def test_rejects_invalid_bulk_size(self):
        with patch.dict("os.environ", {"JACE_SCRYFALL_BULK_SIZE": "100"}, clear=False):
            with self.assertRaisesRegex(ValueError, "JACE_SCRYFALL_BULK_SIZE"):
                app_config()


if __name__ == "__main__":
    unittest.main()
