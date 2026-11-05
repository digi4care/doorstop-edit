---
date: 2026-11-05
topic: "Doorstop Edit Qt/QML met Python behouden versus Rust"
status: brainstorm-source
---

# Brainstorm: Qt/QML voor Doorstop Edit

ReqIF is geparkeerd voor deze brainstorm. Dit document vergelijkt alleen een mogelijke Qt Quick/QML-interface met (A) de huidige Python-logica behouden en (B) Rust-logica via een Qt/QML-binding. Het is geen PRD, ADR of toestemming voor een dev-branch; er is geen branch aangemaakt.

## Problem and context

- De huidige editor is een PySide6 Qt Widgets desktopapp. De gebruiker overweegt een Rust-port met een Qt/QML-bridge en noemt betrouwbaarheid en snelheid bij grote projecten als mogelijke redenen.
- De gebruiker wil eerst de twee combinaties vergelijken: QML met Python behouden versus QML met Rust-logica.
- QML is de declaratieve UI-taal van Qt. De huidige app gebruikt Qt Designer `.ui` Widgets-formulieren, handgeschreven Widgets-views, docks, dialogs en menus.
- Onbekend: of QML op zichzelf als modernere/flexibelere interface wordt gewenst, of vooral als manier om Rust met Qt te verbinden.

## Goals

- Verkennen of QML voordelen geeft voor de interface zonder onnodig de bestaande logica te herschrijven.
- Vergelijken wat Rust toevoegt bovenop dezelfde QML-interface en wat dat kost.
- Toetsen hoe huidige functies (tree, editor, pins, render, links, diff, review, dialogs, docks, WebEngine) behouden worden.
- Mogelijke Rust-motivaties toetsen met concrete metingen of storingen, niet alleen met algemene verwachtingen.

## Constraints and preferences

- **Confirmed preferences:**
  - Eerst brainstormen en beide QML-routes vergelijken.
  - QML-doelen: flexibelere layouts, modernere interactie en theme-aanpassing.
  - Mogelijke Rust-motivaties: betrouwbaarheid en performance op grote projecten.
- **Known technical constraints:**
  - Current app: PySide6 6.11.3, Python 3.11-3.14, Qt Widgets, plus QWebEngineView/QWebChannel.
  - CI covers Linux, Windows, macOS and Python 3.11-3.14.
  - Existing project data/business integration uses Python Doorstop APIs.
- **Unknown:**
  - Team's Rust/QML experience, target timeline, measured project sizes/slow operations, and required packaging/installers.
  - Whether the user wants to replace the UI with QML for UX reasons independent of Rust.
  - Whether a Rust core would retain Python Doorstop APIs through an integration boundary or replace them.
  - Exact CXX-Qt/Qt/PySide6 compatibility and QtWebEngine integration are not tested.

## Explored ideas and alternatives

### A. Keep Python logic; replace Qt Widgets UI with QML

- Qt for Python officially documents QML UI with Python backend objects/signals.
- QML can become a new UI layer while Python remains responsible for Doorstop data and existing application logic.
- Likely less language/runtime scope than adding Rust, but still a substantial UI migration: current Designer forms, dock behavior, tree/list/editor views, dialogs, render view, and WebEngine bridge need equivalents or adapters.
- This route can explore QML's UI value without committing to Rust.

### B. QML UI with Rust logic via Qt binding

- KDAB CXX-Qt documentation demonstrates Rust-defined QObjects used with QML. It is a concrete candidate binding, not a selected dependency.
- Potentially aligns with a Rust strategic direction and native core, but also adds Rust toolchain, C++ compiler/CMake/Qt build integration, a Qt-binding API boundary, and migration decisions for Python Doorstop behavior and Python packaging.
- Does not automatically guarantee better performance or reliability. No app-specific benchmark or CXX-Qt build was run.
- This route combines the UI migration and backend migration, so any regression has more possible causes.

### Baseline / smaller experiment

- Keep the current Qt Widgets UI and measure the reported large-project performance/reliability issues before deciding whether a UI rewrite or language port addresses them.
- A small QML vertical slice using existing Python logic could test the user’s stated UI goals (flexible layouts, modern interaction, theme customization) without also porting the backend. Rust can remain a separate question until its benefits are tied to measured workload or reliability issues. This is an option for exploration, not a decision.

## Evaluation

- **Supported by evidence:**
  - Current UI is Qt Widgets defined in Designer `.ui` plus Python Widgets views. No QML infrastructure was found.
  - PySide6's official Qt for Python docs show integration of Python backend objects with QML via `QQmlApplicationEngine`/QQuickView.
  - CXX-Qt's official guide shows Rust `QObject` integration with QML; documented prerequisites include Rust, Qt, C++ compiler, CMake >=3.24, and `qmake`.
  - Current GUI uses QWebEngineView/QWebChannel for HTML rendering and JS communication; it needs explicit compatibility work in either QML route.
- **Assumptions or interpretations:**
  - Retaining the current Python/Doorstop layer while migrating only the UI may make it easier to isolate QML's benefit; migration effort has not been estimated.
  - Rust may address some reliability/performance goals, but no measurements yet show this is the limiting factor.
- **Counterarguments and risks:**
  - QML changes interface technology, not the Doorstop data/backend architecture by itself.
  - Rust+QML increases migration surface and build-tool requirements; it may duplicate effort if the QML UI has no standalone product value.
  - A QML migration could change behavior, accessibility, docking flexibility, rendering, desktop-native interaction, or cross-platform packaging. These impacts are untested.
  - Current PySide6 and CXX-Qt are not established as a drop-in combined runtime; they represent distinct integration paths (Python↔QML or Rust↔Qt/QML).
- **Confidence and uncertainty:**
  - High confidence in current Widgets architecture and documented official integration examples.
  - Low confidence in migration effort/performance impact until a scoped vertical slice and benchmarks are made.

## Unresolved questions

- Which representative screen should be used to test flexible layout, modern interaction, and theme customization in QML?
- What specific actions on what project sizes feel too slow, and what reliability failures occur?
- Must the Python Doorstop library remain the source of truth, and if so, how would Rust interact with it?
- Which existing WebEngine use cases must stay (HTML/Markdown, PlantUML, links, popup rendering, QWebChannel callbacks)?
- What are target installers and release constraints across Linux, Windows, macOS?
- What Rust/QML expertise is available, and is a long migration affordable?
- What smallest vertical slice would demonstrate value without rewriting all views?

## Evidence and next inquiries

- Repository inventory: `doorstop_edit/main.py`, `main_window.py`, `application.py`, `item_tree/item_tree_view.py`, `item_edit/item_edit_view.py`, `item_render/item_render_view.py`, `doorstop_data.py`, `app_signals.py`, `ui/*.ui`, `tools/gen_ui.py`, `pyproject.toml`, `.github/workflows/test.yml`.
- Official Qt for Python QML integration: https://doc.qt.io/qtforpython-6/tutorials/qmlintegration/qmlintegration.html
- Qt Quick module docs: https://doc.qt.io/qtforpython-6/PySide6/QtQuick/index.html
- KDAB CXX-Qt Getting Started: https://kdab.github.io/cxx-qt/book/getting-started/index.html
- Evidence note: `~/projects/opencode-agents/research/2026-11-05-doorstop-edit-python-qml-vs-rust-qml.md`.
- Next useful inquiry: choose one representative screen and compare a QML+Python slice versus current Widgets; independently measure a real large-project workload before using performance as a Rust decision criterion.

## Handoff notes

Do not select Rust or QML solely from general claims. First clarify whether QML has independent UI value. Keep QML+Python, QML+Rust, and retaining Widgets as separable options. Any later design should explicitly cover the Python Doorstop boundary, WebEngine behavior, build/package matrix, and tests.
