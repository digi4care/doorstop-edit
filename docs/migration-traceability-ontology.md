# Migration traceability graph: schema v1

**Status:** schema-contract voor Beads `.8.1`; dit document definieert de vocabulary, maar implementeert of genereert nog geen graph. De eerste inventaris en kandidaatrelaties staan in [`qml-frontend-analysis.md`](qml-frontend-analysis.md#7-two-distinct-graphontology-scopes).

**Schema-ID:** `doorstop-edit-migration-traceability/1`
**Scope:** één repositorysnapshot van de QML-migratie: requirements, bestaande capabilities, code, tests, Beads en verificatiebewijs.

## 1. Grenzen

- Deze graph ondersteunt review en change-impact van de migratie. Hij is niet de optionele runtime-graph van geopende Doorstop-projecten; die heeft een eigen contract in [`app-knowledge-graph-ontology.md`](app-knowledge-graph-ontology.md).
- De graph is een afgeleide projectie. Doorstop-requirements, capability-inventaris, repositorybestanden, tests, Beads en bewijsartefacten blijven hun eigen bron van waarheid.
- Schema v1 definieert geen opslagengine, gegenereerde index, query-API of CI-integratie. Die horen bij `.8.2` en `.8.3`.
- Dit schema en de graph zijn geen formele compliance- of volledigheidsgarantie. Een ontbrekende relatie blijft zichtbaar als een gap; tooling mag ontbrekend bewijs niet als succes interpreteren.
- IDs zijn stabiel binnen de repository en hun gedefinieerde bron-ID. Ze zijn geen globale identifiers en bevatten geen mutable inhoud zoals titel, header, test-uitkomst of regelnummer.

## 2. Graph-document

Een v1-serialisatie heeft één repositorysnapshot en deze top-level shape. `properties` bevat alleen primitieve waarden; IDs en provenance hebben de betekenis uit dit contract.

```json
{
  "schemaId": "doorstop-edit-migration-traceability/1",
  "repository": { "id": "doorstop-edit", "revision": "<full-git-commit-sha>" },
  "generatedAt": "<ISO-8601 timestamp>",
  "nodes": [
    {
      "id": "cap:CAP-START",
      "type": "Capability",
      "properties": {},
      "provenance": {},
      "freshness": "current",
      "verificationStatus": "unverified",
      "coverageStatus": "notAssessed"
    }
  ],
  "edges": [
    {
      "id": "rel:implementedBy:cap:CAP-START->source:doorstop_edit/main.py",
      "type": "implementedBy",
      "sourceId": "cap:CAP-START",
      "targetId": "source:doorstop_edit/main.py",
      "provenance": {},
      "freshness": "current"
    }
  ]
}
```

`verificationStatus` en `coverageStatus` zijn alleen vereist waar de node of edge een verificatie-/coverageclaim maakt; `freshness` en provenance blijven vereist voor graph-claims. Een ontbrekend of onbekend veld mag niet stilzwijgend een positieve status opleveren.

## 3. Entiteiten en stabiele IDs

Een ID gebruikt de namespace hieronder en de canonieke bronidentifier. Schemaserialisatie bewaart IDs als strings; consumerende tools mogen geen eigen ID-regels afleiden uit labels of presentatievelden.

| Entiteit | ID-regel | Canonieke bron en betekenis |
|---|---|---|
| `Requirement` | `req:{doorstop-uid}` | UID van een expliciete Doorstop-requirement. De inhoud van het requirement blijft in de Doorstop-tree. |
| `Capability` | `cap:{cap-id}` | Bestaande stabiele `CAP-*`-ID uit het capability-register in `qml-frontend-analysis.md`. |
| `Source` | `source:{repo-relative-path}[::{qualified-symbol}]` | Repositorybestand, optioneel met volledig gekwalificeerd symbool. Paden zijn relatief aan repositoryroot, gebruiken `/` en behouden filename-case. |
| `AutomatedTest` | `test:{repo-relative-path}::{pytest-nodeid}` | Testbestand plus pytest node ID; dit identificeert de testlocatie, niet een succesvolle uitvoering. |
| `ManualCase` | `manual:{case-id}` | Handmatige acceptatiecase-ID uit het pariteitsregister, bijvoorbeeld `MA-21`. |
| `BeadsIssue` | `beads:{issue-id}` | Canoniek Beads-issue-ID, inclusief repository-/projectprefix. |
| `Evidence` | `evidence:{repo-relative-path}#{artifact-key}` | Vastgelegd bewijsartefact met een expliciete key, zoals een report-ID of screenshot-ID. Een tijdelijk bestand zonder stabiele key is geen evidence node. |

Een rename van bronbestand, symbool, test-node-ID of Beads-issue-ID verandert de bijbehorende ID en vereist dat relaties opnieuw worden opgebouwd. Titels, beschrijvingen, inhoud, uitkomsten en regelnummers veranderen de ID niet. Een future schema-version mag de regels alleen wijzigen met een expliciete migratie.

## 4. Getypeerde relaties

Edges zijn gericht en bevatten `id`, `type`, `sourceId`, `targetId`, `provenance` en `freshness`. Edge-ID is `rel:{type}:{sourceId}->{targetId}`; parallelle relaties met dezelfde endpoints en hetzelfde type zijn in v1 niet toegestaan. Omgekeerde navigatie is een queryrichting, geen tweede edge.

| Relatie | Richting | Betekenis |
|---|---|---|
| `derivedFrom` | `Capability` → `Requirement` of `Source` | De capability-inventarisatie is expliciet afgeleid van de bron. |
| `implementedBy` | `Capability` → `Source` | De bronlocatie implementeert gedrag van de capability; dit is geen bewijs van parity. |
| `verifiedBy` | `Requirement`/`Capability` → `AutomatedTest`/`ManualCase` | De test of handmatige case verifieert benoemde acceptatiecriteria. |
| `trackedBy` | `Requirement`/`Capability`/`Source`/`AutomatedTest` → `BeadsIssue` | Het issue plant of volgt werk voor het bronobject. |
| `evidencedBy` | `AutomatedTest`/`ManualCase` → `Evidence` | Een specifieke uitvoering of handmatige beoordeling leverde dit artefact op. |
| `impacts` | `Source`/`Capability` → `Requirement`/`Capability`/`AutomatedTest`/`BeadsIssue` | Een expliciet vastgelegde impactrelatie; geen automatische gevolgtrekking uit alleen imports of tekstgelijkenis. |
| `supersedes` | versiegebonden object → versiegebonden object van hetzelfde type | Alleen toegestaan wanneer een expliciete beslissing de vervanging vastlegt; nooit afleiden uit gelijke namen. |

Relaties mogen alleen worden aangemaakt met een verifieerbare bronlocator en provenance. Een relatie zonder die metadata is ongeldig of `unknown`, niet stilzwijgend `verified`.

## 5. Broncitaten en provenance

Een source locator identificeert een controleerbare plek zonder het graph-ID afhankelijk te maken van veranderlijke regels:

```yaml
locator:
  path: doorstop_edit/application.py
  symbol: DoorstopEdit._on_filewatch_callback  # optioneel
  lineStart: 150                              # optioneel, samen met lineEnd
  lineEnd: 184                                # optioneel
  commit: <full-git-commit-sha>
```

- `path` is verplicht voor `Source`, `AutomatedTest` en repositorygebonden `Evidence`; gebruik geen absolute paden.
- `symbol` is optioneel en beschrijft een herkenbare code-eenheid. Het vervangt geen commit-pin.
- `lineStart` en `lineEnd` zijn een 1-based, inclusieve hint en moeten samen voorkomen. Regelranges zijn alleen geldig voor de opgegeven commit; na wijziging van die commit moeten ze opnieuw worden gecontroleerd.
- Voor Doorstop-bronnen citeert provenance de requirement-UID en de bronsectie die in het item is vastgelegd. Voor Beads citeert zij het issue-ID en de gelezen `updated_at`-versie.
- Evidence legt waar toepasselijk command, resultaat, omgeving, commit en meettijd vast. Een testnaam zonder uitvoeringsresultaat is een relatie naar testdefinitie, geen bewijs van geslaagde verificatie.

Elke node/edge bevat provenance met minimaal:

| Veld | Betekenis |
|---|---|
| `sourceKind` | `doorstop`, `capability-register`, `repository`, `test-run`, `manual-review`, `beads` of `evidence-artifact`. |
| `sourceLocator` | De canonieke bron-ID en, voor code/evidence, bovenstaande path/symbol/line/commit locator. |
| `observedAt` | ISO-8601 timestamp waarop de claim is geïnspecteerd of gemeten. |
| `method` | `automated`, `manual` of `derived`, met de checker/command of reviewwijze waar van toepassing. |
| `repositoryRevision` | Volledige Git commit SHA waarop repositoryclaims en regelranges zijn gebaseerd. |

Ontbrekende provenance wordt expliciet als `unknown` behandeld en kan geen geverifieerde edge opleveren.

## 6. Status, freshness en coverage

V1 scheidt verificatiestatus van freshness en coverage; deze begrippen zijn niet uitwisselbaar.

- `verificationStatus`: `verified`, `failed`, `notRun` of `unverified`. Alleen een evidence-link met een waarneembaar resultaat mag `verified` of `failed` dragen.
- `freshness`: `current`, `stale` of `unknown`. `current` vereist dat de bronlocator nog bestaat en bij de opgegeven revision is gecontroleerd. `stale` betekent dat de bron na die revision is veranderd of de locator niet meer valideert. Als de revision of locator niet kan worden gecontroleerd, is de waarde `unknown`.
- `coverageStatus` voor requirements/capabilities: `covered`, `uncovered`, `untestable` of `notAssessed`. `covered` vereist minstens één actuele, passende verification-relatie met resultaat. Een bestaande testdefinitie zonder uitgevoerde evidence is geen coverage.
- Geen status wordt door afwezigheid van data `verified` of `current`; ontbrekende relaties blijven als uncovered/gap rapporteerbaar.
- Een geslaagde test-run geldt alleen voor de vastgelegde commit, Python-/OS-/Qt-omgeving en command. Een latere codewijziging maakt dat bewijs voor de nieuwe revision stale totdat het opnieuw is uitgevoerd.

## 7. Versiebeheer en validatiegrens

De consumer start met `schemaId=doorstop-edit-migration-traceability/1`; `/1` is de major schema-versie. Onbekende major-versies worden niet stilzwijgend als v1 gelezen. Backwards-compatible additieve velden mogen binnen v1 worden toegevoegd met expliciete documentatie; wijzigingen aan ID-regels, endpoint-semantiek of statusbetekenis vereisen een nieuwe major schema-ID (bijvoorbeeld `/2`) en migratie.

Dit contract definieert geen graph-generator of validator. `.8.2` bepaalt hoe Doorstop-, capability-, code-, test- en Beads-bronnen worden verzameld en hoe broken, stale, uncovered of untestable relaties worden gerapporteerd. `.8.3` bepaalt impactvragen en reviewweergaven. Geen van die volgende tickets mag de no-compliance-grens of de hierboven vastgelegde bronsemantiek afzwakken.
