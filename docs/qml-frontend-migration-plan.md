# QML-frontend: analyse en migratieplan

Status: plan en backlog voor een toekomstig, gefaseerd traject. Dit is geen implementatiebesluit over Rust en geen toestemming om de huidige UI voortijdig te verwijderen.

## Doel en grenzen

- Vervang de Qt Widgets-presentatielaag door Qt Quick/QML; behoud voorlopig Python en de bestaande Doorstop-integratie als backend.
- Behoud alle huidige workflows en gedragingen. De Widgets-UI blijft beschikbaar totdat volledige pariteit en platformvalidatie zijn aangetoond en de gebruiker de omschakeling accepteert.
- Neem zowel (1) een traceability-knowledge-graph voor requirements, capabilities, code, tests en Beads als (2) een nieuw, optioneel knowledge-graph-scherm in de applicatie op.
- Werkhypothese: “realtime” betekent actueel na lokale wijzigingen en na externe wijzigingen die de bestaande file watcher detecteert. Leg een meetbare latency-eis pas vast na analyse.
- De prototype-branch demonstreert slechts een editor-slice. Ze bewijst geen featurepariteit, productiearchitectuur, persistente themaprofielen, packaging of KG/ontology-gedrag.

## Analyse van de huidige frontend

Deze inventaris is gebaseerd op broninspectie van de huidige checkout `mvp-1-uv-migration`, niet op een volledige handmatige GUI-acceptatietest. Deze checkout bevat omvangrijke niet-gecommitte wijzigingen; de analyse beschrijft de nu aanwezige bron. Voor implementatie moet de baseline opnieuw worden vastgelegd.

### Opstart, hoofdvenster en voorkeuren

- `doorstop_edit/main.py:36-87`: CLI-start, versie/verbose-opties, root-directory, splash en Qt event loop; zonder root wordt de laatst gebruikte folder gebruikt of kan de gebruiker een folder kiezen.
- `doorstop_edit/application.py:52-168,664-673`: applicatie-/data-opbouw, root/folder, signalen, vensterkoppelingen en lifecycle. `doorstop_edit/crash_log.py` ondersteunt crash logging.
- `doorstop_edit/main_window.py:15-80`: hoofdvenster, geometry/dock-state bewaren en herstellen, huidige dark-teal-stijl.
- `ui/main.ui:102-160,169-198,838-1154`: hoofdvenster, menu's, acties en docks. `application.py:82-119,381-402`: File/View/About/Validate Project-acties en zichtbaarheid van docks.
- `dialogs/setting_dialog.py:120-193` en `settings.py:22-64`: persistente instellingen, fontgrootte, density, spellcheck/taal en onmiddellijke theme-aanpassing.
- Te verifiëren: sneltoetsen, toegankelijkheid, exacte dockinteracties en lokalisatie. Niet gevonden in één inspectie betekent niet bewezen afwezig.

### Documentboom en beheer

- `doorstop_edit/item_tree/item_tree_view.py:24-329`: document/itemboom, niveau/status, selectie, meertermzoekfilter, inactive items tonen, refresh, expand/collapse en contextacties (verwijderen, pinnen, popup, nieuw item).
- `doorstop_edit/application.py:215-338,422-486`: documentselectie, toevoegen/verwijderen, review-all, clear-all-links en levels herschikken.
- Documentverwijdering blokkeert wanneer children bestaan, met foutmelding en zonder gedeeltelijke mutatie (`docs/document-deletion-policy.md`). Item-create bestaat al; dit is iets anders dan document-create.

### Itemeditor, relaties en review

- `doorstop_edit/item_edit/item_edit_view.py:40-624`: itemvelden/attributen, veldvalidatie en level-fixup, vertraagd opslaan, dirty-state, undo, text-wrap/formatting, UID kopiëren, link-picker, links toevoegen/verwijderen, review/unreview, diff en suspect-links wissen.
- Behoud timing, validatiefouten, selectie-/dirty-state, dialoog- en contextacties en review-fingerprint. Pariteit is gedragspariteit, niet alleen dezelfde controls.

### Renderen en preview

- `doorstop_edit/item_render/item_render_view.py:111-281`: Qt WebEngine (`QWebEngineView`/`QWebEnginePage`), `QWebChannel`, worker, navigatiebeleid, view modes, gedeeltelijk renderen/reload, progress, item/document openen en zoekfunctie in de renderer.
- `doorstop_edit/item_render/render_worker.py` en renderhelpers bevatten bestaande Markdown/HTML- en PlantUML-paden. WebEngine, JS-bridge, externe links, popup/itemnavigatie, veiligheidsbeleid en fouten vragen expliciete gelijkwaardigheidstests; platte tekstpreview is geen vervanging.

### Pins, diff, validatie en externe wijzigingen

- `doorstop_edit/pinned_items/pinned_items_view.py:13-63`: pin/unpin en popup-openen.
- `doorstop_edit/dialogs/diff_dialog.py` en `dialogs/differs/`: git- of eenvoudige diffweergave.
- `doorstop_edit/application.py:170-201,504-635`: projectvalidatie, status/resultaten, UI-feedback en worker-lifecycle/shutdown. Triggers zijn tree-load, na succesvolle item-save en expliciet verzoek (`docs/validation-policy.md`).
- `doorstop_edit/doorstop_data.py` en `doorstop_edit/utils/file_watcher.py`: Doorstop-tree, itemdata, save/rebuild en de bestaande Watchdog-monitor. Externe wijziging kan een item herladen of tree rebuild veroorzaken. Geen tweede watcher introduceren.

### Platform, tests en packaging

- `pyproject.toml`: Python 3.11–3.14 en PySide6/Qt WebEngine; `.github/workflows/test.yml` test Linux, Windows en macOS. QML/Quick/WebEngine-deployment en exacte OS-baselines moeten worden geverifieerd.
- Tests in `doorstop_edit/test/` en subpackages dekken onder meer application, data, validation, watcher, rendering, picker, document-management en diff. Koppel ieder bestaand UI-scenario aan een QML-test of expliciete handmatige acceptatiecase; een groene suite alleen bewijst geen UI-pariteit.

## Bevestigd, aangenomen en nog te besluiten

**Bevestigd:** QML wordt de frontendrichting; Python/Doorstop blijft voorlopig de logica- en datalaag; prototypecopy is Engels, productie moet i18n ondersteunen; layoutkeuze staat los van appearance/profiel; geen bestaande functionaliteit laten vallen; knowledge graph/ontology is zowel traceability als app-functie.

**Werkhypotheses:** “realtime” betekent live/actueel na lokale mutaties en externe file-watcher-events; de graph is optioneel en vervangt de bestaande documentboom niet. De requirements-analyse bevestigt of corrigeert dit.

**Open beslissingen:** ontologievocabulaire/formalisme (app-eigen schema versus RDF/OWL of bestaande standaard), identiteit en provenance van nodes/edges, opslag/persistentie, import/export, graph-vragen/filters, latency- en schaalgrenzen, exacte dock-pariteit, toegankelijkheid/i18n en release/cutover. Analyse levert opties en trade-offs; er wordt nu geen standaard of compliance gekozen.

**Beads-conflict:** bestaand epic `doorstop-edit-modernize-uv-todos-55b` zegt “Keep the existing Qt Widgets architecture; no QML”. Dit QML-traject is een afzonderlijk, nieuw vervolg na die modernization/release-scope. Het herschrijft die historische opdracht niet en start geen migratiecode in de huidige vuile checkout.

## Gefaseerde epic-structuur

De uitvoerbare user stories en acceptatiecriteria zijn vastgelegd in Beads. De top-level volgorde:

1. **Analyse en behoudsgarantie** — capability/parity-matrix, state-/event-flow, backendcontract, bestaande tests, risicoregister, platformbaseline en fasering.
2. **QML-shell en Python-integratie** — QML-engine, CLI/startup, QObject/modelcontracten, vensters/panelen, menus, acties, shortcuts, instellingen en lifecycle.
3. **Navigatie en document-/itembeheer** — boom, filtering, contextacties, document-/itemoperaties, review-all en level-ordering.
4. **Itemeditor, links en review** — velden, validatie/save, undo/formatting, link-picker, review/suspect-links en diff.
5. **Render/preview-pariteit** — bestaande Markdown/PlantUML-worker, WebEngine/WebChannel, view modes, zoekfunctie, reload/progress, popup/navigatie en foutafhandeling.
6. **Validatie, watcher en betrouwbaarheid** — bestaande watcher, data-refresh, validatiefeedback/workers, stale-result handling, crash logging en veilige shutdown.
7. **Voorkeuren, theming en inclusieve bediening** — geometry/persistente settings, spellcheck, font/density, Night/Day/Auto, tokenprofielen met opslagbeleid, i18n, keyboard/a11y en platformcontrole.
8. **Traceability-knowledge-graph** — requirements/capabilities/code/tests/Beads als gekoppelde nodes, broncitaten, coverage-gaten, freshness en valideerbare/generatieve trace.
9. **App knowledge graph en ontology** — gebruikersvragen/requirements, schema, mapping van Doorstop, live updates, optionele graph-weergave/navigatie, filtering, performance en opslagbesluiten.
10. **Pariteit, distributie en cutover** — volledige regressie-/OS-matrix, packaging, gefaseerde uitrol, rollback; Widgets-code pas verwijderen na expliciete parity-acceptatie.

## Definition of done

- Elke bestaande capability heeft een gedragsbeschrijving, user story, acceptatiecriteria en test-/handmatig bewijs.
- Geen actie, view, menu, dialoog, shortcut, status, foutpad of data-mutatie verdwijnt stilzwijgend; afwijking vereist expliciete gebruikersbeslissing en requirementwijziging.
- Python/Doorstop blijft de bron van waarheid tenzij een apart besluit die grens wijzigt.
- Testen bewijzen QML↔Python updates, lifecycle, dirty-state, regressies en platformgedrag.
- Widgets wordt pas verwijderd na volledige paritymatrix, cross-platformvalidatie, documentatie en gebruikersacceptatie.
- Geen commit, merge, push of release zonder aparte toestemming.

## Bronnen en bewijsgrenzen

Broninspectie: `doorstop_edit/main.py`, `main_window.py`, `application.py`, `item_tree/item_tree_view.py`, `item_edit/item_edit_view.py`, `item_render/item_render_view.py`, `render_worker.py`, `pinned_items/pinned_items_view.py`, `doorstop_data.py`, `utils/file_watcher.py`, `dialogs/`, `settings.py`, `ui/main.ui`, `pyproject.toml`, CI en tests. Context: `docs/exploration.md`, `docs/validation-policy.md`, `docs/file-watcher.md`, `docs/document-management.md`, `docs/document-deletion-policy.md`, `docs/requirements-traceability.md` en de brainstorm van 2026-11-05. Volledige handmatige GUI-acceptatietest is niet uitgevoerd. Geen applicatiecode is door dit plan aangepast.

Uitgevoerde analyse en pariteitsbaseline: [`docs/qml-frontend-analysis.md`](qml-frontend-analysis.md). Het huidige QObject/property/slot-, fout- en threadcontract staat in [`docs/qml-python-contract.md`](qml-python-contract.md). Deze analyse bevat het capability-register, state/event-flow, bestaande REQ/test-mapping, NOT RUN GUI-cases, architectural options en vastgelegde graph-besluiten.

## Beads-koppelingen

Overkoepelend epic: `doorstop-edit-qml-frontend-migration-plan-lml`. De 10 child-epics: `.1` analyse/pariteit, `.2` QML-shell/Python, `.3` navigatie/documentbeheer, `.4` itemeditor, `.5` render/WebEngine, `.6` validatie/watcher/lifecycle, `.7` settings/theming/i18n, `.8` traceability-knowledge-graph, `.9` app knowledge graph/ontology, `.10` pariteit/packaging/cutover. Elke epic heeft onderliggende Beads user stories met acceptatiecriteria.

De epics voor implementatie zijn afhankelijk gemaakt van `.1`; `.9` vereist daarnaast `.2` en `.8`; `.10` blokkeert op de functionele epics. Het bestaande modernization-epic `doorstop-edit-modernize-uv-todos-55b` is alleen als gerelateerd gekoppeld, niet als blocking dependency.
