# Baseline quality review

Date: 2026-11-02
Scope: automated tests and checks, representative application paths, complexity, security, performance, and architecture. This is a proportional code-quality review, not a formal-standard compliance assessment.

## Verification evidence

- `uv lock --check` — passed.
- `uv run python build.py` — passed; generated build metadata and UI modules.
- `uv run python tools/check_code.py` — passed: Ruff check, Ruff format, and mypy.
- `uv run pytest -ra --color=yes --cov=doorstop_edit --cov-report=term-missing` — 40 passed, one `pkg_resources` deprecation warning; total statement/branch coverage reported as 68%. Qt WebEngine also emitted a non-failing profile/page teardown diagnostic.
- CI configuration (`.github/workflows/test.yml`) covers Ubuntu, macOS, and Windows with Python 3.11–3.14 and uploads Linux/Python 3.11 coverage. CI builds generated resources but does not build and smoke-test a wheel or sdist. No minimum coverage threshold is configured.

## Findings

### P3 — Verified documentation discrepancy: README lists completed validation as TODO

`README.md:30–33` still says “Validating documents and items in a user-friendly manner” is unfinished, while `doorstop_edit/application.py` and `doorstop_edit/test/test_application.py` implement and test project validation feedback. Follow-up: `doorstop-edit-imx.1`.

### P2 — Traceability gap: no Doorstop requirements are tracked in this repository

The repository has no tracked Doorstop requirements tree and the CI workflow has no Doorstop validation/link check. Consequently, this review cannot create reliable Doorstop requirement-to-test links; applicable quality requirements are uncovered or untestable until a source of requirements is established. This is recorded rather than substituting Beads IDs for Doorstop requirement IDs. Follow-up: `doorstop-edit-imx.3`.

### P3 — Recommendations: test/package confidence

- Coverage is 68% overall, with notably low coverage in `item_render/render_worker.py` (23%), `item_render/fragmented_markdown.py` (21%), and `item_edit/item_picker_dialog.py` (30%). These percentages identify where tests are sparse, not proof of defects or a reason by themselves to impose a threshold. Add risk-focused cases around render-worker error/lifecycle behavior and representative markdown rendering. Follow-up: `doorstop-edit-imx.4`.
- CI exercises tests from the source tree but does not install/run the built distribution. A packaging smoke test would catch missing generated/runtime files not exposed by source-tree tests. Follow-up: `doorstop-edit-imx.2`.
- `DoorstopEdit.quit()` waits without a timeout for the validation `QThread` (`application.py:163–169`). Project validators are arbitrary Python and are documented as unsandboxed (`docs/validation-policy.md:30–34`), so a blocked validator could delay shutdown indefinitely. This is a hardening risk, not a reproduced defect; safe cancellation/isolation needs a separate design decision.

No P1/P0 issue or verified application correctness defect was found in this scoped review.

## Follow-up: risk-focused renderer and picker tests (2026-11-02)

Added focused cases for fragmented Markdown, renderer reference-change/progress behavior, and item
picker filtering/selection. Under only these focused tests (not the full-suite run), coverage changed
from the baseline measurements as follows:

| Module | Baseline | Focused tests |
|---|---:|---:|
| `item_render/render_worker.py` | 23% | 41% |
| `item_render/fragmented_markdown.py` | 21% | 77% |
| `item_edit/item_picker_dialog.py` | 30% | 98% |

Command: `uv run pytest doorstop_edit/test/test_render_paths.py doorstop_edit/test/test_item_picker_dialog.py --cov=doorstop_edit.item_render.render_worker --cov=doorstop_edit.item_render.fragmented_markdown --cov=doorstop_edit.item_edit.item_picker_dialog --cov-report=term-missing -q`.
These measurements describe this focused test subset, not total project coverage; no global coverage
threshold is imposed.

## Risk review notes

- No correctness defect was verified in the reviewed watcher/validation paths. In particular, an externally repaired malformed YAML item is reloaded and the derived tree is rebuilt on `tree_changed`; the error row clears.
- No `shell=True`, `eval`, or `exec` use was found in the application Python files inspected. `GitDiffer` invokes Git with an argument list rather than a shell command. This was a scoped source review, not a security audit; custom project Python validators remain executable, unsandboxed code.
- The reviewed data paths are linear in the number of documents/items for lookup, tree building, and validation, with sorting at level-tree nodes. No asymptotic hotspot was identified for the expected desktop workload; large-project validation latency has not been measured.
- No broad architectural rewrite is recommended. The main boundary risk is that Doorstop is shared across UI, watcher, and validation-worker activity; current validation uses a separate disk-backed tree and coalesces overlapping requests.

## Traceability status at baseline review

| Quality area | Evidence in this review | Doorstop requirement link |
|---|---|---|
| Automated test/check execution | CI workflow; commands/results above | Unavailable: no tracked requirements tree |
| Coverage/test gaps | Coverage table and recommendations above | Unavailable: no tracked requirements tree |
| Complexity/security/performance/architecture | Scoped source review notes above | Unavailable: no tracked requirements tree |

No compliance claim is made. At baseline time, follow-up `doorstop-edit-imx.3` was needed before requirement-level traceability could be completed; see the follow-up status below.

## Other follow-up status (2026-11-02)

- `doorstop-edit-imx.2`: CI now builds wheel and source distribution artifacts, then installs the
  built wheel into an isolated environment and imports it from `site-packages`. The sequence passed
  locally on Linux; Windows/macOS runner execution remains a CI check.
- `doorstop-edit-imx.3`: Added an in-repository Doorstop tree with eight requirements drawn only from
  explicit approved docs. The checker validates source/evidence anchors and native file-reference
  paths; CI fails broken links. Six requirements have named evidence; `REQ-004` and `REQ-008` remain
  explicitly uncovered/untestable and are reported without failing the check. This is not a formal-
  compliance claim.

## Isolated test-process finalization

The isolated `doorstop_edit/test/test_application.py` process is expected to exit normally after all
assertions complete when run with the project's pinned dependencies. The Python 3.11 / PySide6 6.12.0
run instead aborts during interpreter finalization; the same test process exits normally with the
pinned PySide6 6.11.3 workaround. Investigation attributes the failure to PySide's cross-version
singleton reference ownership behavior when compiled with Python 3.12 headers, though the exact
published-wheel build provenance and application call site remain unverified. This is a test-process
reliability requirement, not evidence of a user-facing application crash. See the linked research
note for the evidence boundary.
