# Indenture Term Extractor (`indenture`)

Extracts defined terms from credit agreements, CLO indentures and ISDA agreements (PDF or DOCX, with OCR fallback). It's a **β app**: staff only, at `/utilities/indenture/` on the β Apps page.

| | |
|---|---|
| Version | see `config.py` (`1.1.0`); the git tag is `v<version>` |
| Live site | yes: `"external": True`, pinned as `indenture@<version>` in the server allowlist |
| Data | run history and term presets through `AppDataStore` (the `PluginData` table). Uploads and EDGAR exhibits are processed in a temporary folder and not kept. |
| Code | `core_logic/` holds file conversion, OCR, text processing, term extractors and strategies; `services.py` is the glue; `views.py` has the index, results, history, presets and CSV download |
| Packages | pdfplumber, PyMuPDF, python-docx, pytesseract and related packages come from the **site's** `requirements.txt` |

**Tests** (from the site folder on the PC):
~~~
venv\Scripts\python.exe manage.py test_plugins
~~~
**Release:** bump `version` in `config.py`, then:
- on the PC: `_builds\plugin-tools\plugin_release.ps1 -Slug indenture`;
- on the server: `plugin_deploy.sh indenture <version>`.

See the site's `docs/server_cheatsheet.md` §4.
