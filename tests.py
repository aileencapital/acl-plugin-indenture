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
