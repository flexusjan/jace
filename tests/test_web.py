from base64 import b64encode
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from jace.refresher import RefreshStatus, refresh_status_payload
from jace.storage import HistoryPoint, ReportPage, ReportRow
from jace.web import (
    basic_auth_credentials,
    card_history_payload,
    cards_payload,
    import_payload,
    import_requests_from_payload,
    report_pagination_payload,
)
from jace.importer import ImportFailure, ImportResult


class WebPayloadTest(unittest.TestCase):
    def test_cards_payload_includes_change_and_history(self):
        row = ReportRow(
            id="entry-1",
            scryfall_id="card-1",
            name="Sol Ring",
            set_code="soc",
            collector_number="128",
            source_url="https://scryfall.com/card/soc/128",
            has_cached_image=False,
            has_image_url=True,
            quantity=1,
            condition="NM",
            language="English",
            currency="EUR",
            latest_price=Decimal("0.72"),
            latest_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            first_price=Decimal("0.50"),
            first_captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        history = {
            "entry-1": [
                HistoryPoint(
                    captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    price=Decimal("0.50"),
                    currency="EUR",
                ),
                HistoryPoint(
                    captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                    price=Decimal("0.72"),
                    currency="EUR",
                ),
            ]
        }

        payload = cards_payload([row], history)

        self.assertEqual(payload["cards"][0]["name"], "Sol Ring")
        self.assertEqual(payload["cards"][0]["scryfall_id"], "card-1")
        self.assertTrue(payload["cards"][0]["has_image_url"])
        self.assertEqual(payload["cards"][0]["change"], "0.22")
        self.assertEqual(len(payload["cards"][0]["history"]), 2)

    def test_cards_payload_omits_history_by_default(self):
        row = ReportRow(
            id="entry-1",
            scryfall_id="card-1",
            name="Sol Ring",
            set_code="soc",
            collector_number="128",
            source_url="https://scryfall.com/card/soc/128",
            has_cached_image=False,
            has_image_url=True,
            quantity=1,
            condition="NM",
            language="English",
            currency="EUR",
            latest_price=Decimal("0.72"),
            latest_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            first_price=Decimal("0.50"),
            first_captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        payload = cards_payload([row])

        self.assertNotIn("history", payload["cards"][0])

    def test_cards_payload_includes_pagination_metadata(self):
        page = ReportPage(rows=[], total_count=201, total_value=Decimal("12.50"), currency="EUR")

        payload = cards_payload([], pagination=report_pagination_payload(page, page=2, page_size=100))

        self.assertEqual(payload["pagination"]["page"], 2)
        self.assertEqual(payload["pagination"]["page_size"], 100)
        self.assertEqual(payload["pagination"]["total_count"], 201)
        self.assertEqual(payload["pagination"]["total_pages"], 3)
        self.assertEqual(payload["pagination"]["total_value"], "12.50")

    def test_card_history_payload_formats_points(self):
        payload = card_history_payload(
            [
                HistoryPoint(
                    captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    price=Decimal("0.50"),
                    currency="EUR",
                )
            ]
        )

        self.assertEqual(payload["history"][0]["price"], "0.50")

    def test_cards_payload_keys_history_by_scryfall_id(self):
        rows = [
            ReportRow(
                id="entry-1",
                scryfall_id="card-1",
                name="Counterspell",
                set_code="clu",
                collector_number="84",
                source_url="https://scryfall.com/card/clu/84",
                has_cached_image=False,
                has_image_url=False,
                quantity=1,
                condition="NM",
                language="English",
                currency="EUR",
                latest_price=Decimal("0.25"),
                latest_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                first_price=Decimal("0.25"),
                first_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
            ReportRow(
                id="entry-2",
                scryfall_id="card-2",
                name="Counterspell",
                set_code="dmr",
                collector_number="45",
                source_url="https://scryfall.com/card/dmr/45",
                has_cached_image=False,
                has_image_url=False,
                quantity=1,
                condition="NM",
                language="English",
                currency="EUR",
                latest_price=Decimal("0.75"),
                latest_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                first_price=Decimal("0.75"),
                first_captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ),
        ]
        history = {
            "entry-1": [HistoryPoint(datetime(2026, 2, 1, tzinfo=timezone.utc), Decimal("0.25"), "EUR")],
            "entry-2": [HistoryPoint(datetime(2026, 2, 1, tzinfo=timezone.utc), Decimal("0.75"), "EUR")],
        }

        payload = cards_payload(rows, history)

        self.assertEqual(payload["cards"][0]["history"][0]["price"], "0.25")
        self.assertEqual(payload["cards"][1]["history"][0]["price"], "0.75")

    def test_import_requests_from_text_payload(self):
        requests = import_requests_from_payload({"source": "text", "text": "2 Sol Ring [LTC]"})

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].quantity, 2)
        self.assertEqual(requests[0].name, "Sol Ring")
        self.assertEqual(requests[0].set_code, "ltc")

    def test_import_requests_from_csv_payload(self):
        requests = import_requests_from_payload(
            {
                "source": "csv",
                "text": '"Count","Name","Edition","Collector Number"\n"3","Counterspell","clu","84"\n',
            }
        )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].quantity, 3)
        self.assertEqual(requests[0].name, "Counterspell")
        self.assertEqual(requests[0].set_code, "clu")
        self.assertEqual(requests[0].collector_number, "84")
        self.assertEqual(requests[0].condition, "NM")
        self.assertEqual(requests[0].language, "English")

    def test_import_payload_includes_failures(self):
        payload = import_payload(
            ImportResult(total=2, processed=2, imported=1, failures=[ImportFailure("Bad Card", "not found")])
        )

        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["processed"], 2)
        self.assertEqual(payload["imported"], 1)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["failures"][0]["name"], "Bad Card")

    def test_refresh_status_payload_includes_progress(self):
        payload = refresh_status_payload(
            RefreshStatus(running=True, total=3, processed=2, refreshed=1, failed=1),
            interval_seconds=3600,
        )

        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["processed"], 2)
        self.assertEqual(payload["refreshed"], 1)
        self.assertEqual(payload["failed"], 1)

    def test_basic_auth_credentials_parses_valid_header(self):
        token = b64encode("alice:secret".encode("utf-8")).decode("ascii")

        self.assertEqual(basic_auth_credentials(f"Basic {token}"), ("alice", "secret"))

    def test_basic_auth_credentials_rejects_invalid_headers(self):
        self.assertIsNone(basic_auth_credentials(None))
        self.assertIsNone(basic_auth_credentials("Bearer token"))
        self.assertIsNone(basic_auth_credentials("Basic not-base64"))
        self.assertIsNone(basic_auth_credentials("Basic bm9jb2xvbg=="))


if __name__ == "__main__":
    unittest.main()
