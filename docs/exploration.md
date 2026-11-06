# Phase 0: Codebase exploration

Date: 2026-11-01
Scope: read-only exploration; no application code changed.

## Commands and findings

Commands from the PRD were run read-only:

```sh
cat pyproject.toml
find doorstop_edit -type f -name '*.py' | sort
grep -rnE 'QWebEngineView|QTextBrowser' doorstop_edit/
grep -rnEi 'plantuml|mermaid' doorstop_edit/ pyproject.toml
```

Python inspection was run through `uv run --no-project --with 'doorstop==3.0.2'` (no Poetry command was used). The project itself has not yet been migrated to uv, so the project environment and GUI were not launched in this phase.

### Package and runtime configuration

- `pyproject.toml` declares package version `0.1.4`, Python `>=3.9,<3.12`, and `doorstop >=3.0.2,<4`.
- Packaging configuration and the development dependency group still use `[tool.poetry]` and `[tool.poetry.group.dev.dependencies]`; `poetry.lock` is present and no `uv.lock` exists yet.
- The project entry point is `doorstop_edit.main:main`; `python -m doorstop_edit` delegates to it through `doorstop_edit/__main__.py`.
- The main window and application lifecycle are wired in `doorstop_edit/application.py`; `DoorstopEdit.start()` builds the tree and starts the watcher, while `quit()` stops it.

### Preview, item tree, and diagram support

- The preview uses Qt WebEngine `QWebEngineView`, not `QTextBrowser` (`doorstop_edit/item_render/item_render_view.py`). Markdown is rendered to HTML by `RenderWorker` and displayed in the WebEngine view.
- `plantuml-markdown` is a runtime dependency and `fragmented_markdown.py` configures the PlantUML server URL. No Mermaid references were found in `doorstop_edit/` or `pyproject.toml`.
- The item tree is implemented in `doorstop_edit/item_tree/item_tree_view.py`. It displays document items, their levels and headers, with existing visual states for review, active/inactive, suspect links, and normative items.
- `doorstop_edit/doorstop_data.py` owns the loaded Doorstop tree and provides document/item lookup, persistence, and rebuild operations.

### File watcher: correction to the PRD baseline

- A watcher is already implemented using `watchdog`, not Qt's `QFileSystemWatcher`: `doorstop_edit/utils/file_watcher.py` observes document paths, and `DoorstopData` wires its callbacks in `doorstop_edit/doorstop_data.py`.
- Modified files reload the matching item; created, deleted, and moved paths trigger a tree rebuild. The watcher is stopped when the application quits.
- The README's current TODO list names document add/remove and user-friendly document/item validation; it does **not** list a file watcher. Therefore, the PRD statement that the watcher is an unimplemented TODO is stale. MVP 2 should audit and harden the existing watcher rather than add a second watcher.
- Debouncing, deleted-root handling, and temporary-file watcher tests remain verification items; this exploration did not establish that those behaviors meet the PRD's proposed criteria.

### Validation and document management

- Application startup builds a Doorstop tree through `doorstop.build(cwd=..., root=...)` and loads it in `DoorstopData.rebuild()`.
- No call to Doorstop's `tree.validate()` was found in the application. The existing item editor's `QValidator` validates individual widget input; it is not whole-tree Doorstop validation.
- The README TODOs include adding/removing documents and user-friendly validation. Item creation is already implemented through `selected_document.add_item()` in `application.py`; this does not imply document creation/removal is implemented.

## Conclusion

The PRD's broad direction fits the current Doorstop-based application and the existing Qt Widgets architecture. Its baseline needs two corrections before implementation: the watcher already exists and must be hardened, and the document-management tasks should distinguish document operations from the already-supported item creation. Whole-tree validation is not currently wired into the UI. See the related Beads issues for Doorstop 3.0.2 API constraints and open behavior decisions.

## Evidence limits

- This was source inspection, not a GUI run or a manual test on the low-end VPS.
- The app was not launched because the project still uses Poetry metadata and has not yet been migrated to uv.
- Dependency API checks used Doorstop 3.0.2 via an ephemeral uv environment; no dependency files were changed.
