import unittest
from base64 import b64encode
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from jace.importer import ImportFailure, ImportResult
from jace.models import CardRequest
from jace.refresher import RefreshStatus, refresh_status_payload
from jace.storage import (
    CollectionMode,
    CollectionStats,
    HistoryPage,
    HistoryPoint,
    ReportPage,
    ReportRow,
    ValueHistoryPoint,
)
from jace.web import (
    ImportJob,
    ImportJobs,
    PriceTrackerHandler,
    TooManyJobsError,
    basic_auth_credentials,
    card_history_payload,
    cards_payload,
    collection_mode_payload,
    format_collection_stats,
    history_pagination_payload,
    history_sample_payload,
    import_payload,
    import_requests_from_payload,
    moxfield_sync_requests_from_csv,
    rendered_index_html,
    report_pagination_payload,
    request_origin_allowed,
    scryfall_image_url_allowed,
    summary_payload,
    value_history_payload,
)


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
            condition="Near Mint",
            language="English",
            finish="Non-Foil",
            currency="EUR",
            latest_price=Decimal("0.72"),
            latest_captured_at=datetime(2026, 2, 1, tzinfo=UTC),
            first_price=Decimal("0.50"),
            first_captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        history = {
            "entry-1": [
                HistoryPoint(
                    captured_at=datetime(2026, 1, 1, tzinfo=UTC),
                    price=Decimal("0.50"),
                    currency="EUR",
                ),
                HistoryPoint(
                    captured_at=datetime(2026, 2, 1, tzinfo=UTC),
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
            condition="Near Mint",
            language="English",
            finish="Non-Foil",
            currency="EUR",
            latest_price=Decimal("0.72"),
            latest_captured_at=datetime(2026, 2, 1, tzinfo=UTC),
            first_price=Decimal("0.50"),
            first_captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        payload = cards_payload([row])

        self.assertNotIn("history", payload["cards"][0])

    def test_cards_payload_includes_pagination_metadata(self):
        page = ReportPage(
            rows=[], total_count=201, total_value=Decimal("12.50"), currency="EUR"
        )

        payload = cards_payload(
            [], pagination=report_pagination_payload(page, page=2, page_size=100)
        )

        self.assertEqual(payload["pagination"]["page"], 2)
        self.assertEqual(payload["pagination"]["page_size"], 100)
        self.assertEqual(payload["pagination"]["total_count"], 201)
        self.assertEqual(payload["pagination"]["total_pages"], 3)
        self.assertEqual(payload["pagination"]["total_value"], "12.50")

    def test_card_history_payload_formats_points(self):
        payload = card_history_payload(
            [
                HistoryPoint(
                    captured_at=datetime(2026, 1, 1, tzinfo=UTC),
                    price=Decimal("0.50"),
                    currency="EUR",
                )
            ]
        )

        self.assertEqual(payload["history"][0]["price"], "0.50")

    def test_card_history_payload_includes_pagination_metadata(self):
        history_page = HistoryPage(rows=[], total_count=201)

        payload = card_history_payload(
            [],
            pagination=history_pagination_payload(history_page, page=2, page_size=100),
        )

        self.assertEqual(payload["pagination"]["page"], 2)
        self.assertEqual(payload["pagination"]["page_size"], 100)
        self.assertEqual(payload["pagination"]["total_count"], 201)
        self.assertEqual(payload["pagination"]["total_pages"], 3)

    def test_card_history_payload_includes_sample_metadata(self):
        history_page = HistoryPage(rows=[], total_count=600, sampled=True)

        payload = card_history_payload(
            [], sample=history_sample_payload(history_page, sample_size=500)
        )

        self.assertEqual(payload["sample"]["sample_size"], 500)
        self.assertEqual(payload["sample"]["sampled_count"], 0)
        self.assertEqual(payload["sample"]["total_count"], 600)
        self.assertTrue(payload["sample"]["sampled"])

    def test_value_history_payload_formats_points(self):
        payload = value_history_payload(
            [
                ValueHistoryPoint(
                    captured_at=datetime(2026, 1, 1, tzinfo=UTC),
                    total_value=Decimal("12.50"),
                    currency="EUR",
                )
            ]
        )

        self.assertEqual(payload["history"][0]["total_value"], "12.50")
        self.assertEqual(payload["history"][0]["currency"], "EUR")

    def test_summary_payload_formats_homepage_widget_values(self):
        report = ReportPage(
            rows=[], total_count=2331, total_value=Decimal("12426.12"), currency="EUR"
        )
        payload = summary_payload(
            report,
            [
                ValueHistoryPoint(
                    captured_at=datetime(2026, 5, 3, tzinfo=UTC),
                    total_value=Decimal("12022.93"),
                    currency="EUR",
                ),
                ValueHistoryPoint(
                    captured_at=datetime(2026, 7, 4, tzinfo=UTC),
                    total_value=Decimal("12426.12"),
                    currency="EUR",
                ),
            ],
        )

        self.assertEqual(payload["cards"], 2331)
        self.assertEqual(payload["total_value"], "12426.12 EUR")
        self.assertEqual(payload["change"], "+403.19 EUR")
        self.assertEqual(payload["currency"], "EUR")

    def test_summary_payload_handles_missing_history(self):
        report = ReportPage(rows=[], total_count=0, total_value=None, currency=None)

        payload = summary_payload(report, [])

        self.assertEqual(payload["cards"], 0)
        self.assertIsNone(payload["total_value"])
        self.assertIsNone(payload["change"])
        self.assertIsNone(payload["currency"])

    def test_format_collection_stats_includes_storage_counts(self):
        text = format_collection_stats(
            CollectionStats(cards=2, tracked_entries=3, snapshots=5)
        )

        self.assertEqual(text, "cards=2 tracked_entries=3 snapshots=5")

    def test_collection_mode_payload_formats_sync_timestamp(self):
        payload = collection_mode_payload(
            CollectionMode("moxfield", datetime(2026, 7, 26, 20, 41, tzinfo=UTC))
        )

        self.assertEqual(payload["mode"], "moxfield")
        self.assertEqual(payload["last_sync_at"], "2026-07-26T20:41:00+00:00")

    def test_rendered_index_html_uses_configured_theme(self):
        self.assertIn('data-theme="dark"', rendered_index_html(True))
        self.assertIn('data-theme="light"', rendered_index_html(False))
        self.assertIn('href="/app.css?v=', rendered_index_html(True))
        self.assertIn('src="/app.js?v=', rendered_index_html(True))

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
                condition="Near Mint",
                language="English",
                finish="Non-Foil",
                currency="EUR",
                latest_price=Decimal("0.25"),
                latest_captured_at=datetime(2026, 2, 1, tzinfo=UTC),
                first_price=Decimal("0.25"),
                first_captured_at=datetime(2026, 2, 1, tzinfo=UTC),
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
                condition="Near Mint",
                language="English",
                finish="Foil",
                currency="EUR",
                latest_price=Decimal("0.75"),
                latest_captured_at=datetime(2026, 2, 1, tzinfo=UTC),
                first_price=Decimal("0.75"),
                first_captured_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        ]
        history = {
            "entry-1": [
                HistoryPoint(datetime(2026, 2, 1, tzinfo=UTC), Decimal("0.25"), "EUR")
            ],
            "entry-2": [
                HistoryPoint(datetime(2026, 2, 1, tzinfo=UTC), Decimal("0.75"), "EUR")
            ],
        }

        payload = cards_payload(rows, history)

        self.assertEqual(payload["cards"][0]["history"][0]["price"], "0.25")
        self.assertEqual(payload["cards"][1]["history"][0]["price"], "0.75")

    def test_import_requests_from_text_payload(self):
        requests = import_requests_from_payload(
            {"source": "text", "text": "2 Sol Ring [LTC]"}
        )

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
        self.assertEqual(requests[0].condition, "Near Mint")
        self.assertEqual(requests[0].language, "English")

    def test_moxfield_sync_requires_exact_printing_identifiers(self):
        with self.assertRaisesRegex(ValueError, "Edition and Collector Number"):
            moxfield_sync_requests_from_csv("Count,Name\n1,Sol Ring\n")

    def test_moxfield_sync_merges_duplicate_rows(self):
        requests = moxfield_sync_requests_from_csv(
            "Count,Name,Edition,Collector Number,Condition\n1,Sol Ring,ltc,314,NM\n2,Sol Ring,ltc,314,NM\n"
        )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].quantity, 3)

    def test_import_payload_includes_failures(self):
        payload = import_payload(
            ImportResult(
                total=2,
                processed=2,
                imported=1,
                failures=[ImportFailure("Bad Card", "not found")],
            )
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
        token = b64encode(b"alice:secret").decode("ascii")

        self.assertEqual(basic_auth_credentials(f"Basic {token}"), ("alice", "secret"))

    def test_basic_auth_credentials_rejects_invalid_headers(self):
        self.assertIsNone(basic_auth_credentials(None))
        self.assertIsNone(basic_auth_credentials("Bearer token"))
        self.assertIsNone(basic_auth_credentials("Basic not-base64"))
        self.assertIsNone(basic_auth_credentials("Basic bm9jb2xvbg=="))

    def test_request_origin_allows_same_host(self):
        self.assertTrue(
            request_origin_allowed("https://example.com:8180/path", "example.com:8180")
        )
        self.assertFalse(
            request_origin_allowed("https://evil.example.com", "example.com")
        )
        self.assertFalse(request_origin_allowed("not-a-url", "example.com"))

    def test_scryfall_image_url_must_be_https_scryfall_host(self):
        self.assertTrue(
            scryfall_image_url_allowed(
                "https://cards.scryfall.io/normal/front/card.jpg"
            )
        )
        self.assertFalse(
            scryfall_image_url_allowed("http://cards.scryfall.io/normal/front/card.jpg")
        )
        self.assertFalse(
            scryfall_image_url_allowed("https://evil-scryfall.io/normal/front/card.jpg")
        )

    def test_send_json_ignores_client_disconnect(self):
        class BrokenWriter:
            def write(self, body):
                raise BrokenPipeError()

        handler = PriceTrackerHandler.__new__(PriceTrackerHandler)
        handler.wfile = BrokenWriter()
        handler.send_response = lambda status: None
        handler.send_header = lambda name, value: None
        handler.end_headers = lambda: None

        handler._send_json({"ok": True})

    @patch.dict("os.environ", {"JACE_MAX_IMPORT_JOBS": "1"}, clear=False)
    def test_import_jobs_rejects_when_active_limit_is_reached(self):
        jobs = ImportJobs()
        jobs._jobs["job-1"] = ImportJob(
            id="job-1", total=1, currency="eur", status="running"
        )

        with self.assertRaises(TooManyJobsError):
            jobs.create(
                [CardRequest(quantity=1, name="Sol Ring")],
                "eur",
                "postgresql://example",
            )

    def test_moxfield_sync_is_exclusive_with_other_mutating_jobs(self):
        jobs = ImportJobs()
        jobs._jobs["job-1"] = ImportJob(
            id="job-1", total=1, currency="eur", kind="import", status="running"
        )

        with self.assertRaisesRegex(TooManyJobsError, "Wait for running imports"):
            jobs._create_job("moxfield_sync", 1, "eur")

        jobs._jobs["job-1"] = ImportJob(
            id="job-1", total=1, currency="eur", kind="moxfield_sync", status="running"
        )
        with self.assertRaisesRegex(TooManyJobsError, "Manual imports are unavailable"):
            jobs._create_job("import", 1, "eur")


if __name__ == "__main__":
    unittest.main()
