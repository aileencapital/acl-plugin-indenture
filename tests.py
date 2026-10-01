"""
Tests for the indenture extractor mini-app.

These cannot run on EC2 today (the production aileen_app role lacks
CREATEDB; see handover_addendum_2026-05-19 trigger-watch). They are
written so that the Stage 3 smell-test on Windows / SQLite can run
them.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from analytics_app.functions._framework.data_store import AppDataStore
from . import services


User = get_user_model()


def _make_staff(username: str = "tester") -> "User":
    user = User.objects.create_user(
        username=username,
        password="x",
        is_staff=True,
    )
    return user


class IndexViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.user = _make_staff()
        self.client.force_login(self.user)

    def test_index_renders(self) -> None:
        resp = self.client.get(reverse("indenture:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Indenture Term Extractor")
        self.assertContains(resp, "Strategy")
        self.assertContains(resp, 'name="file"')
        self.assertContains(resp, 'name="strategy"')

    def test_extract_rejects_bad_extension(self) -> None:
        # An in-memory upload: Windows can't reopen a NamedTemporaryFile while
        # it is still open, so the old temp-file version failed there (26 Sep).
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("bad.txt", b"not a pdf or docx", content_type="text/plain")
        resp = self.client.post(
            reverse("indenture:extract"),
            {"file": upload, "strategy": "Smart", "mode": "auto"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("indenture:index"))


class PresetCrudTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.user = _make_staff()
        self.client.force_login(self.user)

    def test_create_read_update_delete(self) -> None:
        # Create.
        resp = self.client.post(
            reverse("indenture:presets_list"),
            {"name": "Credit Agreement basics", "terms": "Applicable Margin\nInterest Coverage Ratio"},
        )
        self.assertEqual(resp.status_code, 302)
        sets = services.list_preset_sets(self.user)
        self.assertEqual(len(sets), 1)
        set_id = sets[0]["set_id"]
        self.assertEqual(sets[0]["terms"], ["Applicable Margin", "Interest Coverage Ratio"])

        # Read.
        resp = self.client.get(reverse("indenture:presets_detail", args=[set_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Credit Agreement basics")

        # Update.
        resp = self.client.post(
            reverse("indenture:presets_detail", args=[set_id]),
            {
                "action": "save",
                "name": "Credit Agreement basics v2",
                "terms": "Applicable Margin\nAdjusted Term SOFR\nEvent of Default",
            },
        )
        self.assertEqual(resp.status_code, 302)
        refreshed = services.get_preset_set(self.user, set_id)
        self.assertEqual(refreshed["name"], "Credit Agreement basics v2")
        self.assertEqual(len(refreshed["terms"]), 3)

        # Delete.
        resp = self.client.post(
            reverse("indenture:presets_detail", args=[set_id]),
            {"action": "delete"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(services.get_preset_set(self.user, set_id))


class CsvDownloadTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.user = _make_staff()
        self.client.force_login(self.user)

    def test_csv_round_trip(self) -> None:
        run = {
            "filename": "sample.pdf",
            "strategy": "Smart",
            "mode": "auto",
            "preset_set_id": None,
            "pages_processed": 1,
            "terms_found": 2,
            "duration_ms": 5,
            "processed_at": "2026-05-20T00:00:00+00:00",
            "results": [
                {
                    "term": "Applicable Margin",
                    "page": "1",
                    "definition": "the margin applicable to each Loan",
                    "confidence": 0.95,
                    "method": "NLP_Fuzzy",
                },
                {
                    "term": "Event of Default",
                    "page": "2",
                    "definition": "any event listed in Section 7",
                    "confidence": 1.0,
                    "method": "Regex_Pattern",
                },
            ],
        }
        run_id = services.save_run(self.user, run)
        resp = self.client.get(reverse("indenture:download", args=[run_id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("text/csv"))
        body = resp.content
        # UTF-8 BOM as the CLI emits.
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        text = body.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], ["Term", "Page", "Definition", "Confidence", "Method"])
        self.assertEqual(rows[1][0], "Applicable Margin")
        self.assertEqual(rows[2][0], "Event of Default")


class HistoryRetentionTests(TestCase):
    def test_history_trims_to_max(self) -> None:
        user = _make_staff("retentiontester")
        store = AppDataStore(app_slug=services.APP_SLUG, user=user)
        # Seed 52 runs with distinct processed_at so order is deterministic.
        for i in range(52):
            services.save_run(user, {
                "filename": f"f{i}.pdf",
                "strategy": "Smart",
                "mode": "auto",
                "preset_set_id": None,
                "pages_processed": 1,
                "terms_found": 0,
                "duration_ms": 1,
                "processed_at": f"2026-05-19T00:{i:02d}:00+00:00",
                "results": [],
            })
        keys = store.list_keys(prefix="run:")
        self.assertEqual(len(keys), services.MAX_HISTORY)


# ── EDGAR (1.1.0): synthetic fixtures only; the site helper is mocked, so no network ──

import datetime
from unittest import mock

from analytics_app.edgar import EdgarError, ExhibitFile

from . import views
from .core_logic import html_to_pdf

SYNTHETIC_CIK = "0000000001"
SYNTHETIC_ACC = "0000000001-26-000001"


def _exhibit(filename="ex41.pdf", content=b"%PDF-1.4 synthetic fixture"):
    return ExhibitFile(content=content, metadata={
        "filename": filename, "content_type": "application/pdf", "accession": SYNTHETIC_ACC,
        "form": "8-K", "filing_date": datetime.date(2026, 1, 2), "document_type": "EX-4.1"})


FAKE_RUN = {"pages_processed": 1, "terms_found": 1, "duration_ms": 5,
            "results": [{"term": "Synthetic Term", "page": "1", "definition": "made up",
                         "confidence": 1.0, "method": "test"}]}


class EdgarExtractTests(TestCase):
    def setUp(self) -> None:
        self.user = _make_staff("edgar")
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse("indenture:extract_from_edgar")
        self.data = {"cik": SYNTHETIC_CIK, "accession": SYNTHETIC_ACC, "filename": "ex41.pdf"}

    def test_route_name_and_post_only(self) -> None:
        self.assertEqual(self.url, "/utilities/indenture/edgar/")
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_stages_runs_and_discards(self) -> None:
        seen = {}

        def fake_run(file_path, **kwargs):
            seen["path"] = file_path
            with open(file_path, "rb") as fh:
                seen["bytes"] = fh.read()
            return FAKE_RUN

        with mock.patch("analytics_app.edgar.get_exhibit", return_value=_exhibit()) as get, \
                mock.patch.object(services, "run_extraction", side_effect=fake_run):
            resp = self.client.post(self.url, self.data)
        get.assert_called_once_with(SYNTHETIC_CIK, SYNTHETIC_ACC, "ex41.pdf")
        self.assertEqual(seen["bytes"], b"%PDF-1.4 synthetic fixture")
        self.assertTrue(seen["path"].endswith("ex41.pdf"))
        self.assertFalse(os.path.exists(seen["path"]))          # discarded with its folder
        self.assertEqual(resp.status_code, 302)
        run = services.list_runs(self.user)[0]
        stored = services.get_run(self.user, run["run_id"])
        self.assertEqual(stored["source"], "EDGAR")
        self.assertEqual(stored["accession"], SYNTHETIC_ACC)
        self.assertNotIn(SYNTHETIC_CIK, str({k: v for k, v in stored.items() if k != "accession"}))

    def test_html_exhibit_is_converted_to_pdf_first(self) -> None:
        def fake_convert(path, out_dir):
            pdf = os.path.join(out_dir, "converted_temp.pdf")
            with open(pdf, "wb") as fh:
                fh.write(b"%PDF-1.4 converted")
            return pdf

        with mock.patch("analytics_app.edgar.get_exhibit",
                        return_value=_exhibit("ex41.htm", b"<html>synthetic</html>")), \
                mock.patch.object(views, "html_to_pdf", side_effect=fake_convert) as conv, \
                mock.patch.object(services, "run_extraction", return_value=FAKE_RUN) as run:
            self.client.post(self.url, {**self.data, "filename": "ex41.htm"})
        self.assertTrue(conv.call_args.args[0].endswith("ex41.htm"))
        self.assertTrue(run.call_args.kwargs["file_path"].endswith("converted_temp.pdf"))

    def test_unsupported_type_is_refused(self) -> None:
        with mock.patch("analytics_app.edgar.get_exhibit", return_value=_exhibit("g1.jpg")), \
                mock.patch.object(services, "run_extraction") as run:
            resp = self.client.post(self.url, {**self.data, "filename": "g1.jpg"}, follow=True)
        run.assert_not_called()
        self.assertContains(resp, "Unsupported exhibit type")

    def test_edgar_error_goes_back_with_a_message(self) -> None:
        with mock.patch("analytics_app.edgar.get_exhibit",
                        side_effect=EdgarError("That file is not one of the filing's documents.")), \
                mock.patch.object(services, "run_extraction") as run:
            resp = self.client.post(self.url, self.data, follow=True)
        run.assert_not_called()
        self.assertContains(resp, "not one of the filing")
        self.assertNotContains(resp, SYNTHETIC_CIK)

    def test_missing_fields(self) -> None:
        with mock.patch("analytics_app.edgar.get_exhibit") as get:
            resp = self.client.post(self.url, {"cik": SYNTHETIC_CIK})
        get.assert_not_called()
        self.assertEqual(resp.status_code, 302)

    def test_index_offers_edgar_without_javascript(self) -> None:
        html = self.client.get(reverse("indenture:index")).content.decode()
        self.assertIn(f'action="{self.url}"', html)
        self.assertIn('href="/utilities/edgar/"', html)
        self.assertNotIn("onclick=", html)


class HtmlToPdfTests(TestCase):
    """html_to_pdf on synthetic EDGAR-shaped files (the SGML wrapper EDGAR serves)."""

    WRAPPED = (b"<DOCUMENT>\n<TYPE>EX-4.1\n<SEQUENCE>2\n<FILENAME>ex41.htm\n<TEXT>\n"
               b"<html><body><p>\"Business Day\" means any day other than a Saturday.</p>"
               b"<img src=\"missing.jpg\"><script>alert(1)</script></body></html>\n"
               b"</TEXT>\n</DOCUMENT>\n")

    def _text(self, pdf_path: str) -> str:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return "".join(page.get_text() for page in doc)

    def test_html_inside_the_edgar_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "ex41.htm")
            with open(src, "wb") as fh:
                fh.write(self.WRAPPED)
            out = html_to_pdf(src, d)
            self.assertTrue(out.endswith("ex41_temp.pdf"))
            text = self._text(out)
        self.assertIn("Business Day", text)
        self.assertNotIn("<TYPE>", text)
        self.assertNotIn("EX-4.1", text)          # the wrapper's header is not rendered
        self.assertNotIn("alert", text)

    def test_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "ex101.txt")
            with open(src, "wb") as fh:
                fh.write(b"\"Lender\" means a <synthetic> party.\n")
            text = self._text(html_to_pdf(src, d))
        self.assertIn("<synthetic>", text)
