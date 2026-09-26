"""
Views for the indenture extractor mini-app.

GET-only renderers and POST handlers for: index/upload, the
extraction endpoint, CSV download, the presets CRUD pages, and run
history.

Authentication is handled by the framework — no view-level
``@login_required`` (authoring contract §3.3).
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)

from . import services

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".pdf", ".docx")


def _csv_filename(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename or "indenture"))[0]
    return f"Extracted_Terms_{base}.csv"


@require_GET
@ensure_csrf_cookie
def index(request: HttpRequest) -> HttpResponse:
    prefs = services.get_user_prefs(request.user)
    presets = services.list_preset_sets(request.user)
    return render(request, "indenture/index.html", {
        "strategies": services.STRATEGIES,
        "modes": services.MODES,
        "preset_sets": presets,
        "prefs": prefs,
    })


@require_POST
def extract(request: HttpRequest) -> HttpResponse:
    uploaded = request.FILES.get("file")
    strategy = request.POST.get("strategy", "Smart")
    mode = request.POST.get("mode", "auto")
    preset_set_id = request.POST.get("preset_set") or None
    prefer_first = request.POST.get("prefer_first") == "on"

    if uploaded is None:
        messages.error(request, "Please choose a PDF or DOCX file to upload.")
        return redirect("indenture:index")

    ext = os.path.splitext(uploaded.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        messages.error(
            request,
            f"Unsupported file type {ext!r}. Upload a .pdf or .docx file.",
        )
        return redirect("indenture:index")

    if strategy not in services.STRATEGIES:
        messages.error(request, f"Unknown strategy: {strategy!r}.")
        return redirect("indenture:index")
    if mode not in services.MODES:
        messages.error(request, f"Unknown mode: {mode!r}.")
        return redirect("indenture:index")

    preset_terms = None
    if mode == "preset":
        if not preset_set_id:
            messages.error(request, "Choose a preset set when running in preset mode.")
            return redirect("indenture:index")
        preset = services.get_preset_set(request.user, preset_set_id)
        if preset is None:
            messages.error(request, "The selected preset set could not be found.")
            return redirect("indenture:index")
        preset_terms = preset.get("terms") or []
        if not preset_terms:
            messages.error(request, "The selected preset set has no terms.")
            return redirect("indenture:index")

    with tempfile.TemporaryDirectory(prefix="indenture-") as tmpdir:
        safe_name = os.path.basename(uploaded.name) or f"upload{ext}"
        tmp_path = os.path.join(tmpdir, safe_name)
        try:
            with open(tmp_path, "wb") as f:
                for chunk in uploaded.chunks():
                    f.write(chunk)
        except OSError as e:
            logger.exception("Failed to write upload to temp dir")
            messages.error(request, f"Could not stage the upload: {e}")
            return redirect("indenture:index")

        try:
            run = services.run_extraction(
                file_path=tmp_path,
                strategy=strategy,
                mode=mode,
                preset_terms=preset_terms,
                prefer_first=prefer_first,
            )
        except FileNotFoundError as e:
            logger.exception("Upload disappeared during extraction")
            messages.error(request, str(e))
            return redirect("indenture:index")
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("indenture:index")
        except RuntimeError as e:
            logger.exception("Extraction dependency failure")
            messages.error(
                request,
                f"Extraction failed: {e}. Contact the architect.",
            )
            return redirect("indenture:index")
        except Exception as e:  # pragma: no cover — last-resort guard
            logger.exception("Unexpected extraction failure")
            messages.error(request, f"Unexpected error: {e}")
            return redirect("indenture:index")

    run_record = {
        "filename": uploaded.name,
        "strategy": strategy,
        "mode": mode,
        "preset_set_id": preset_set_id,
        "pages_processed": run["pages_processed"],
        "terms_found": run["terms_found"],
        "results": run["results"],
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": run["duration_ms"],
    }
    run_id = services.save_run(request.user, run_record)
    services.save_user_prefs(request.user, strategy, mode, preset_set_id)

    return redirect("indenture:history_detail", run_id=run_id)


@require_GET
def download_csv(request: HttpRequest, run_id: str) -> HttpResponse:
    run = services.get_run(request.user, run_id)
    if run is None:
        return HttpResponse("Run not found.", status=404)
    body = services.run_to_csv_bytes(run)
    filename = _csv_filename(run.get("filename", "indenture"))
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def presets_list(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        terms_blob = request.POST.get("terms", "")
        terms = [t.strip() for t in terms_blob.splitlines() if t.strip()]
        try:
            services.save_preset_set(request.user, name=name, terms=terms)
            messages.success(request, f"Saved preset set {name!r}.")
        except ValueError as e:
            messages.error(request, str(e))
        return redirect("indenture:presets_list")

    sets = services.list_preset_sets(request.user)
    return render(request, "indenture/presets_list.html", {
        "preset_sets": sets,
    })


@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def presets_detail(request: HttpRequest, set_id: str) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "delete":
            services.delete_preset_set(request.user, set_id)
            messages.success(request, "Preset set deleted.")
            return redirect("indenture:presets_list")
        name = request.POST.get("name", "").strip()
        terms_blob = request.POST.get("terms", "")
        terms = [t.strip() for t in terms_blob.splitlines() if t.strip()]
        try:
            services.save_preset_set(
                request.user, name=name, terms=terms, set_id=set_id,
            )
            messages.success(request, "Preset set updated.")
        except ValueError as e:
            messages.error(request, str(e))
        return redirect("indenture:presets_detail", set_id=set_id)

    preset = services.get_preset_set(request.user, set_id)
    if preset is None:
        return HttpResponse("Preset set not found.", status=404)
    return render(request, "indenture/presets_detail.html", {
        "preset": preset,
        "terms_blob": "\n".join(preset.get("terms", [])),
    })


@require_GET
def history(request: HttpRequest) -> HttpResponse:
    runs = services.list_runs(request.user)
    return render(request, "indenture/history.html", {"runs": runs})


@require_GET
def history_detail(request: HttpRequest, run_id: str) -> HttpResponse:
    run = services.get_run(request.user, run_id)
    if run is None:
        return HttpResponse("Run not found.", status=404)
    return render(request, "indenture/history_detail.html", {
        "run_id": run_id,
        "run": run,
        "download_url": reverse("indenture:download", args=[run_id]),
    })
