---
date: 2026-11-05
topic: "Doorstop Edit multi-project, ReqIF en mogelijke Rust/QML-richting"
status: brainstorm-source
---

# Brainstorm: multi-project editor, ReqIF-uitwisseling en Rust/QML

Dit is een brainstormbron, geen PRD, ontwerpbesluit of toestemming om een branch te maken. De gebruiker wil eerst brainstormen. Er is geen dev-branch aangemaakt.

## Problem and context

- De huidige Doorstop Edit-sessie opent één project/root; de gebruiker wil meerdere projecten vanuit één draaiende editor beheren zodat niet voor elk project een aparte editor gestart hoeft te worden.
- De gebruiker heeft drie HTML-layoutprototypes gezien en vindt Atlas (1) en Commandocentrum (2) goed. In een prototype is een projectdropdown gewenst als meer dan één project open is; bij één project moet alleen de projectnaam staan.
- De gebruiker stemde in met één `Indeling`-switcher voor Atlas/Commandocentrum, apart van theme-instellingen (zoals lettergrootte/dichtheid). Layout wisselen moet volgens de voorlopige mock de huidige project/document/item/selectie behouden.
- Twee mogelijke toekomstige onderwerpen zijn ReqIF-uitwisseling en een mogelijke port van Python/Qt naar Rust met een Qt/QML-binding. De gebruiker vroeg eerst hoe het referentieproject Doorhole ermee omgaat.

## Goals

- Meerdere projecten vanuit één editor-instantie kunnen openen en wisselen.
- ReqIF-informatie kunnen ontvangen en terugleveren. De gebruiker koos zowel importeren als exporteren en noemde round-trip-uitwisseling.
- Voor herimport van gewijzigde eisen de verschillen vergelijken en per verschil kunnen kiezen wat over te nemen, in plaats van stil te overschrijven.
- Rust wordt overwogen vanwege betrouwbaarheid en performance bij grote projecten; de gebruiker noemt ook een Qt/QML-bridge.

## Constraints and preferences

- **Confirmed preferences:**
  - Eerst brainstormen; geen branch of implementatie gestart.
  - ReqIF-basis: formele OMG ReqIF 1.2-conformiteit (de gebruiker koos dit nadat “ISO-certificering” als mogelijk onjuiste term was verduidelijkt).
  - Round-trip conflictbeleid: verschillen vergelijken en per verschil kiezen.
  - Multi-project selector als dropdown alleen wanneer meer dan één project open is.
  - Atlas/Commandocentrum via een aparte `Indeling`-switcher; theme blijft apart.
- **Unknown or tentative constraints:**
  - Er is geen genoemd ISO-nummer of afzonderlijke certificeringseis.
  - Geen concrete partner-tool, ReqIF-voorbeeldbestand of uitwisselingsproces genoemd.
  - Niet duidelijk welke ReqIF-attributen/relaties/formatting absoluut behouden moeten blijven.
  - Rust-bridge, verpakking en Qt-versiecombinatie zijn niet lokaal getest.
  - Performance- of betrouwbaarheidspijn is niet gemeten; de doelen zijn gebruikersmotivaties, nog geen aangetoonde tekortkomingen.

## Explored ideas and alternatives

### ReqIF als productfunctie

- **Confirmed direction:** import en export zijn allebei gewenst; gebruikers willen een round-trip kunnen uitvoeren.
- **Conflict handling chosen for exploration:** bewaar genoeg context om een nieuwe externe levering met de eerder geïmporteerde versie te vergelijken; toon verschillen en laat een gebruiker kiezen wat overgenomen wordt. Dit is een gewenste workflow, geen gedetailleerd ontwerp.
- **Open mapping problem:** bepalen hoe externe ReqIF-identifiers verbonden blijven met Doorstop UIDs, en hoe eisen, hiërarchie, attributen, links/relaties en mogelijke bijlagen worden gemapt.
- **Alternative not chosen:** de externe versie automatisch laten winnen (minder reviewwerk, risico op verlies van lokale wijzigingen), of Doorstop als exclusieve bron beschouwen (exporteert lokaal werk terug, maar vereist duidelijke eigenaarschap-afspraken).

### Mogelijke implementatierichtingen

1. **ReqIF bouwen binnen de huidige Python/PySide-app.** Houdt productfunctie en taalport los van elkaar; migratie niet nodig om de uitwisselingsbehoefte te testen. Librarykeuze en mapping zijn nog niet onderzocht.
2. **Een Rust-component als eerste geïsoleerde pilot.** Kan een technische brug toetsen, maar koppelt ReqIF-risico’s aan Rust-integratie.
3. **Rust-kern met bestaande Qt/PySide-interface behouden.** Mogelijke incrementele port; concrete bridge naar bestaande app en distributie moeten onderzocht worden.
4. **Rust met QML als volledige UI-koers.** Geeft de mogelijkheid om UI én kern te vernieuwen, maar is een grotere UI-migratie dan alleen de backend port.

Geen van deze alternatieven is gekozen. ReqIF is een gebruikersfunctie; Rust/QML is een mogelijke technische koers. Ze hoeven niet aan elkaar gekoppeld te worden.

### Multi-project en layout

- Doorhole is geen voorbeeld van ReqIF-round-trip. Het opent meerdere requirement documents/sets als tabs binnen één `doorstop.build()`-tree, niet meerdere onafhankelijke projectroots; het schrijft itemwijzigingen direct naar Doorstop-items.
- De huidige Doorstop Edit multi-project- en layout-switcherweergave bestaat alleen als HTML-mockup, niet als geïmplementeerde functionaliteit.

## Evaluation

- **Supported by evidence:**
  - Doorhole README noemt tabs voor alle requirement sets; `doorhole.py` bouwt één Doorstop-tree en maakt per document een tab. Editable item attributes worden direct opgeslagen via `item.set_attributes(...)` en `item.save()`.
  - De onderzochte Doorhole-repository bevat geen ReqIF-import/export of synchronisatie/conflictafhandeling.
  - De officiële OMG-catalogus publiceert ReqIF 1.2 als formele OMG-specificatie met normatieve machineleesbare schema's. De specificatie bespreekt one-way en round-trip exchange scenario's en stelt conformiteitseisen.
  - ReqIF-formatconformiteit is niet hetzelfde als een ISO-certificering. Geen specifieke ISO-norm is door de gebruiker genoemd; onderzoek heeft niet vastgesteld dat ReqIF zelf een ISO-certificering is.
  - CXX-Qt-documentatie laat Rust-`QObject`s zien die met QML worden gebruikt; de documented build prerequisites omvatten o.a. C/C++ compiler, CMake 3.24+, Rust toolchain, Qt en `qmake`.
- **Assumptions or interpretations:**
  - Voor re-import kan de editor een baseline bewaren en een conflict-/diff-weergave aanbieden. De exacte betekenis van “per verschil” (per veld, attribuut of requirement) is nog niet vastgelegd.
  - De gebruiker bedoelt met de “Qt/QML bridge” mogelijk CXX-Qt of een vergelijkbare Rust–Qt-binding; de specifieke library is niet bevestigd.
- **Counterarguments and risks:**
  - Formele ReqIF-conformiteit alleen garandeert niet dat willekeurige toolketens dezelfde betekenis aan custom attributes of processen geven; partner-compatibiliteit en interpretatieafspraken moeten getest worden.
  - Per-difference merge UI kan complex worden; automatische overwrites zijn eenvoudiger maar kunnen lokale of externe wijzigingen verliezen.
  - Een Rust/QML port kan meer build, toolchain en UI-rewrite werk veroorzaken dan de ReqIF-functie zelf. Er is nog geen benchmark die een Rust-migratie rechtvaardigt.
  - De bestaande PySide6-verpakking en een CXX-Qt/QML-app zijn niet als drop-in compatibel bewezen.
- **Confidence and uncertainty:**
  - Hoog over het beschreven gedrag van Doorhole en de status van OMG ReqIF 1.2, gebaseerd op repo-broncode en officiële OMG-pagina's.
  - Laag over welke ReqIF-dekking de gebruiker werkelijk nodig heeft zonder een echte partnerworkflow of sample.
  - Laag over Rust/QML-keuze zonder build-/packaging-proef en meetbare baseline.

## Unresolved questions

- Welke partner-tool(s) leveren en consumeren de ReqIF-bestanden?
- Betekent round-trip in de praktijk dezelfde eisen heen en terug, of ontvangt Doorstop ook nieuwe/afgeleide eisen die vervolgens terug naar de partner gaan?
- Welke gegevens moeten bij import/export behouden blijven (IDs, relaties, custom attributes, formatting, bijlagen, metadata)?
- Moet conflictselectie op requirement-, attribuut- of veldniveau werken? Wat gebeurt er met eisen die aan één kant verwijderd zijn?
- Is er een echte ISO-/DIN- of contractuele eis naast OMG ReqIF 1.2? Zo ja, welk nummer en welke scope?
- Welke gemeten betrouwbaarheid/performanceproblemen bij grote projecten wil Rust oplossen? Hoe groot zijn die projecten en welke handelingen zijn traag of foutgevoelig?
- Is Rust vooral bedoeld voor de kern/backend, of is de UI naar QML te migreren ook een doel op zichzelf?
- Moeten multi-projecten dezelfde projectstatus, projectwisselgedrag en selector uit de prototypes krijgen? Hoe worden projecten toegevoegd, verwijderd en heropend?

## Evidence and next inquiries

- Doorhole repository: https://github.com/sevendays/doorhole (`README.md:40-47`; `doorhole.py:383-417,428-450,743-749`).
- OMG ReqIF 1.2 formal spec and normative files: https://www.omg.org/spec/ReqIF/1.2/ and https://www.omg.org/spec/ReqIF/1.2/PDF.
- prostep ivip ReqIF fact sheet: https://www.prostep.org/en/medialibrary/fact-sheets/requirements-interchange-format-reqif.
- CXX-Qt official Getting Started guide: https://kdab.github.io/cxx-qt/book/getting-started/index.html.
- Research notes: `~/projects/opencode-agents/research/2026-11-05-doorhole-reqif-and-conformance.md` and `~/projects/opencode-agents/research/2026-11-05-rust-qt-qml-bridge-brainstorm.md`.
- Next useful inquiry: use a real partner ReqIF file (or anonymized sample) and its matching target tool to validate schema, identity retention, field mapping, and re-import behavior before choosing implementation language.

## Handoff notes

A later design process should start from a real import/edit/export scenario and the intended partner tool. Treat OMG ReqIF 1.2 conformance as the confirmed format target, while keeping any separate ISO certification requirement unresolved. Do not assume Doorhole provides ReqIF behavior: it only edits one Doorstop tree with document tabs. Keep ReqIF capability and Rust/QML migration as separate decisions unless the user later explicitly chooses ReqIF as the Rust pilot. No branch or code implementation is authorized by this brainstorm.
