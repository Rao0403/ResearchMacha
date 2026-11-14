# Testing and acceptance

Automated checks are offline. Backend fixtures force mock mode, remove OpenAI credentials, disable the application worker and reject external HTTP. Tests invoke worker handlers against isolated fixtures. Browser tests intercept API requests; they do not use developer uploads or a paid backend.

## Commands

From the repository root:

~~~powershell
cd backend
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
cd ..\frontend
cmd /c npm test -- --run
cmd /c npm exec tsc -- -p tsconfig.app.json --noEmit --incremental false
cmd /c npm run build
cmd /c npm run test:e2e
~~~

Install Chromium once when preparing a fresh development environment:

~~~powershell
cd frontend
cmd /c npx playwright install chromium
~~~

MySQL locking/concurrency tests require TEST_MYSQL_URL pointing to a local account permitted to create/drop disposable databases. The fixture creates unique research_macha_test_* databases and drops only those names. Without that variable, MySQL tests are skipped. GitHub Actions configures a dedicated MySQL service; it also runs frontend tests, typechecking, a production build and Chromium tests.

Migrations are exercised on fresh and legacy fixtures. Normal local upgrades use:

~~~powershell
cd backend
.\.venv\Scripts\python.exe -B -m alembic upgrade head
~~~

Do not use reset scripts or destructive SQL for an upgrade.

## What the tests establish

- Legacy rows survive additive migration; new schema constraints are installed.
- MySQL claims, uniqueness, recovery and note-edit conflicts behave correctly.
- Repeated approval/analyze/generate/chat requests do not create duplicate active work.
- GET polling/reopening and exports perform no writes or model calls.
- Failed reanalysis preserves prior results and personal notes.
- Stale synthesis/comparison generations cannot replace newer work.
- Required import/analysis failures block final generation.
- Unsupported citation IDs, wrong-paper references and invalid excerpts are rejected.
- Embedding incompatibility and provider/vector outages remain explicit.
- Upload limits and malformed batches do not leave partial ownership.
- Library reuse avoids another paper analysis and notifies dependent projects.
- Markdown/BibTeX/CSV retain warnings and stored result provenance.
- Only explicitly selected, in-scope personal notes are exported.
- Bibliography fields are not invented; special characters are escaped.
- CSV handles quotes, Unicode, newlines and formula-like cells.
- Browser interaction, source navigation, notes reopening and downloads work across 1440, 1280, 1024 and 390-pixel widths, with serious/critical accessibility checks.

The saved-workspace integration test runs upload → extraction/analysis → library reuse → research/comparison → notes → read-only exports with a mock provider. It proves contracts and persistence, not live model accuracy.

## Manual acceptance with a small credit budget

Use already-processed papers wherever possible. Generation/reanalysis/query embeddings still cost money; reopening, saving personal notes and exporting do not.

1. Open a known paper. Check body coverage beyond the abstract, including a later methods/results page.
2. Verify one result citation against the PDF. Confirm page, quoted passage, metric/dataset and interpretation.
3. Ask a grounded question and one follow-up, then reopen the paper. Check chat history and reading position.
4. Create a page-linked personal critique; save, edit and reopen it. Reanalysis must leave it intact.
5. Compare two ready library papers with a specific evaluation goal. Check limitations/conditions and follow one source link back to the reader.
6. Reopen the comparison through Compare; ensure opening alone does not generate again.
7. Reopen a project through Projects. If revising evidence, verify the old brief is marked and remains readable until a replacement succeeds.
8. Export Markdown with one chosen personal note. Open the file and check quotations, references, warnings and local-link labels.
9. Export BibTeX; review unknown metadata and special characters. Import into the user's reference tooling if available.
10. Export comparison CSV and inspect it in a spreadsheet. Verify dimensions and source provenance agree with the saved result.
11. At laptop/mobile widths, check overflow, keyboard focus and whether the PDF remains dominant.
12. Back up work before using the product for valuable research; see [data and recovery](data-and-recovery.md).

Exercise outages/restarts with offline fixtures instead of deliberately burning paid calls. Do not describe an automated mock result as a live quality/cost benchmark.

## Screenshot capture

See [walkthrough](walkthrough.md). CAPTURE_DOCS_SCREENSHOTS is opt-in and writes fixture UI images only. It does not record private research data.

## Validation record

Checked on 2026-11-14: 201 backend tests (including real MySQL integration), 39 frontend tests, TypeScript checking, production build and 36 browser checks across four widths. Targeted export/workspace tests were rerun after download/CORS integration fixes. Compose configuration, the installed migration head and local documentation links were also checked.

Test counts can change; rerun the commands after changes. Fresh/legacy schema and MySQL concurrency fixtures were exercised; no new live OpenAI evaluation, fresh dependency reinstall or hosted deployment was performed during export completion.
