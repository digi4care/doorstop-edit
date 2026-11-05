# App Knowledge Graph: ontology v1 en competency questions

**Status:** ontwerpcontract voor Beads `.9.1`; nog geen claim van volledige implementatie of compliance.
**Schema:** `doorstop-edit-app-graph/1`.
**Doel:** een optionele, in-memory projectie voor relatieverkenning, impactanalyse en live review-/suspect-link-/validatiestatus.

## 1. Grenzen en invarianten

- De geopende Doorstop-tree en de projectbestanden blijven de enige bron van waarheid. De graph is read-only en opnieuw opbouwbaar; wijzigingen gebeuren via bestaande Python/Doorstop-use-cases.
- De graph staat los van de migration-traceability graph uit `.8` (requirements → code/tests/Beads). Deze ontology beschrijft uitsluitend de geopende Doorstop-projectinhoud.
- V1 is project-scoped, app-native en getypeerd. Geen graph database, persistente cache, RDF/OWL- of JSON-LD-vocabulaire/export. Voeg later alleen interoperabiliteit toe na een concreet uitwisselingsgebruik.
- Nodes en edges bewaren waarden en provenance, nooit `doorstop.Document`, `doorstop.Item` of `UID`-objecten. Na `tree_changed`/`item_saved` wordt alleen uit de actuele tree een nieuwe projectie gebouwd; oude snapshots worden vervangen.
- Cycles worden als relaties behouden. Traversal gebruikt een `visited`-set en eindigt dus ook bij cyclische input. Een ontbrekend target wordt expliciet getoond, niet stilzwijgend verwijderd.
- Project, document, item en relatie-status zijn verschillende concepten. Een item-attribute zoals `active` is geen aparte node tenzij een latere query daar reden toe geeft.

## 2. Competency questions

1. **Relaties:** Welke items linkt dit item aan (`Doorstop Item.links` / `parent_items`), welke items linken ernaar (`child_items`), en welke link is suspect of unresolved?
2. **Impact:** Welke directe en transitieve items zijn aan dit item gekoppeld via inkomende Doorstop-links? Toon het pad en stop cycli zonder resultaten te dupliceren.
3. **Documentstructuur:** In welk document zit een item; wat is het parent-document (`Document.parent`) en welke child-documents/items vallen eronder?
4. **Review:** Is een item volgens Doorstop op dit moment reviewed? Welke bronvelden tellen mee in de review-stamp? V1 toont actuele status en stamp-inputs, geen historische verklaring welke edit de status ongeldig maakte.
5. **Suspect links:** Welke opgeslagen links hebben een stamp die niet overeenkomt met de huidige target-stamp; naar welke target verwijzen zij?
6. **Validatie:** Welke actuele validation findings horen bij een item, en welke zijn project-breed? Wat is de severity, tekst, validatierevisie en versheid van die resultaten?
7. **Zoeken/filteren:** Welke items voldoen aan UID/header, document, level, active/normative/derived, review/suspect of validation severity-filters?
8. **Provenance:** Uit welk projectbestand, Doorstop-veld of validation-resultaat komt elke node/edge/status? Kan de gebruiker van een graph-item naar de bestaande document-/itemselectie navigeren?
9. **Consistentie:** Na lokale save/review/linkwijziging of bestaand file-watcher-event, welke graphstatus is gewijzigd en werd die zichtbaar binnen één seconde?
10. **Lege/onvolledige data:** Kan de graph tonen dat een project geen links/findings heeft, of dat een item, linktarget of validatierun ontbreekt/mislukt, zonder dat “onbekend” als “geldig” wordt geïnterpreteerd?

## 3. Getypeerde ontology

Node- en edge-IDs zijn stabiel binnen één geopende projectroot en zijn niet bedoeld als globale/interoperabele identifiers. Scope bij elk ID is `projectId`, afgeleid van de opgeloste root voor de duur van die projectcontext. Heropenen/herbouwen van dezelfde projectroot geeft dezelfde document- en item-IDs. Geen ID hangt af van headertekst, volgorde, level of bestandsmtime.

| Type | V1 identiteit | Canonieke gegevens en semantiek | Doorstop-herkomst |
|---|---|---|---|
| `Project` | `project:{root-id}` | Op dit moment geopende root; graph bevat één project. | `DoorstopData.root`; rootpad alleen als projectprovenance. |
| `Document` | `document:{prefix}` | Prefix, pad relatief aan root, parent-prefix, item count en load/error state. Parent-child relatie volgt `Document.parent`; geen afleiding uit directory-namen. | `DoorstopData.get_documents()`, `Document.prefix/path/parent`. |
| `Item` | `item:{uid}` | UID, owning-document ID, level, header, text-snippet (optioneel voor zoekresultaat), `active`, `normative`, `derived`, `reviewed`, load state. Level en flags blijven attributes, geen aparte nodes. | `DoorstopData.iter_items()`, `Item.uid/path/level/header/text/active/normative/derived/reviewed`. |
| `UnresolvedItem` | `unresolved-item:{uid}` | Placeholder voor een UID waarnaar gelinkt wordt maar die niet in de actuele tree gevonden is; geen verzonnen document, pad of attributes. | UID uit `Item.links`; missende target via Doorstop tree lookup. |
| `ValidationFinding` | `finding:{run-id}:{ordinal}` | Severity (`error`, `warning`, `info`), message, optionele item-UID, current/stale state. Niet-itemgebonden finding blijft op projectniveau. | `ValidationFinding` uit `collect_validation`; validatierun levert root/revision/job-id en completion/error metadata. |

| Relatie | Richting | Betekenis |
|---|---|---|
| `containsDocument` | Project → Document | Document behoort tot de geopende projecttree. |
| `containsItem` | Document → Item | Item behoort tot het Doorstop-document dat het iteratiepad oplevert. |
| `childDocumentOf` | Child Document → Parent Document | De child-documentconfig noemt parent-prefix; geen item-link. |
| `linksTo` | Source Item → target Item/UnresolvedItem | Native richting: `source.links` bevat de target UID; Doorstop noemt dit ook een parent link. |
| `reportedFor` | ValidationFinding → Item/Project | Een finding met bestaande item-UID wijst naar dat item; ontbrekende/geen UID wijst naar Project. |

Elke relatie is een getypeerde immutable edge met `id`, `sourceId`, `targetId`, `relationType`, relation-status en provenance. `linksTo`-edges hebben `linkState=ok|suspect|unresolved`; inverse `linkedFrom` voor UI/impact is een queryrichting, geen tweede opgeslagen edge. De edge-ID is `link:{source-uid}:{target-uid}`. De edges voor containment en `childDocumentOf` krijgen IDs uit het type en de endpoint-IDs.

## 4. Statussemantiek en provenance

### Item review-status

Gebruik Doorstop `Item.reviewed` als enige bron: Doorstop vergelijkt de opgeslagen reviewed-stamp met `Item.stamp(links=True)`. Toon `reviewed` of `needsReview`; interpreteer de opgeslagen hash niet zelf en verander hem niet. `unknown` wordt gebruikt wanneer de itemdata niet geladen kon worden. Reviewstatus is een actuele Doorstop-berekening, geen onafhankelijke graph-entiteit. Een huidige stamp vertelt niet welke historische edit de review ongeldig maakte; v1 bewaart geen wijzigingshistorie. De inputs van `stamp(links=True)` zijn UID, text, ref, references, links en geconfigureerde `document.extended_reviewed`-attributen.

### Suspect-link-status

Voor elke native link `source.links` naar UID `target`, vergelijk de opgeslagen link-stamp met `target.stamp()`, gelijk aan het bestaande gedrag in `links_to_list_widget`. Gelijke stamps → `ok`; afwijkende stamp → `suspect`; missende target → `unresolved`. Geen path- of tekstheuristiek om ontbrekende UID's te raden. `Item.cleared` is een bruikbare Doorstop-aggregaatbron, maar de graph projecteert status per edge zodat impact/pad zichtbaar blijft.

### Validatie-status

Validatie blijft de bestaande `collect_validation`/`validation_helper`-logica gebruiken; graph code dupliceert geen Doorstop-validatieregels. Elke run krijgt `runId`, `projectId`, input `contentRevision`, start-/eindtijd en state `notRun|running|succeeded|failed`. Findings worden pas `current` als ze horen bij de actuele root en revision. Na een wijziging wordt de laatste run `stale`/`running` totdat een run voor de nieuwe revision klaar is. Bij een mislukte run worden de laatste findings niet als actuele waarheid gepresenteerd; de fout en oude revision blijven zichtbaar.

### Provenancevelden

Elke node/edge/status krijgt `Provenance`: project-scoped source path (relatief aan root waar mogelijk), source kind (`document-config`, `item-file`, `validation-result`, `derived`), source key (prefix/UID/field), event (`initial-load`, `local-save`, `watcher-reload`, `tree-rebuild`, `validation`), `contentRevision`, `graphGeneration` en observatietijd. Graph edges afgeleid uit links citeren het source-itempad/UID/`links` en target-UID; suspect-status citeert daarnaast de target-stampvergelijking. Findings citeren validation run/contentRevision en `item_uid` indien aanwezig. Absolute paden buiten de projectroot worden niet als graph-ID gebruikt.

## 5. Update- en foutcontract

- Houd twee tellers apart: `contentRevision` stijgt uitsluitend na een geaccepteerde Doorstop-contentwijziging/rebuild; `graphGeneration` stijgt wanneer een nieuwe graphsnapshot of statuspublicatie verschijnt, waaronder een validation-resultaat. Een validation-resultaat verhoogt dus nooit `contentRevision`. Een onveranderde rebuild mag een nieuwe `graphGeneration` publiceren; er wordt geen bestaand graph-object bewaard met mutabele Doorstop-referenties.
- Elke succesvolle lokale Doorstop-mutatie en elk succesvol watcher-event moet een normalized `contentChanged`-event opleveren. De graph projecteert na dit event; `tree_changed` en `item_saved` blijven voor bestaande consumenten behouden. Breng mutaties die nu geen event uitsturen (met name `DoorstopData.restore_item()` en itemverwijdering vanuit de tree) achter een DoorstopData-use-case die `contentChanged` uitzendt. Document create/remove/rebuild en link/review/attribute-save moeten hetzelfde contract volgen; dubbel renderen op zowel een legacy event als normalized event wordt door één revision/event-token voorkomen. De graph start geen eigen filesystem watcher.
- Updates zijn revision-tagged. Een resultaat voor een oude projectroot/`contentRevision` wordt verworpen. Een mislukte root-switch behoudt de vorige valide snapshot; een succesvolle switch vervangt die en wist selectie die niet bij de nieuwe tree hoort.
- `ValidationRun.inputContentRevision` wordt vastgelegd bij start. Findings zijn `current` als root en `inputContentRevision` nog overeenkomen met de huidige content; na een contentmutatie zijn eerdere findings `stale` totdat een run voor die contentrevision slaagt. Alleen `graphGeneration` stijgt bij publicatie van de run-resultaten.
- Validatie draait via bestaand GUI-vrij subprocess-contract, niet synchroon tijdens paint/graph layout. Oude validation-resultaten zijn stale tijdens een nieuwe contentrevision/run.
- De meetgrens is van lokale commit (`save_item`/review/link-use-case) of watcher reload-event tot `graphChanged` en gewijzigde QML-modeldata; target ≤1.0s per gecontroleerde update op de vastgelegde benchmarkfixture; median, p95 en maximum worden daarnaast gerapporteerd. Een vertraagde of mislukte validatie mag de overige relatiegraph niet blokkeren.
- Item-loadfouten moeten expliciet bij de graph-adapter aankomen via DoorstopData-loadresultaat/error-state (UID, message, pad, contentrevision), niet alleen als logregel. De projection toont dan een itemnode met UID/path en `loadState=error` en gebruikt geen oude cached attributes als actueel; na een succesvolle load verdwijnt de error-state. Bepaal bij implementation of een per-UID error registry in DoorstopData of een gestructureerde load-resultaat-event het smalste contract is. Project-buildfouten worden via bestaand root/error-pad getoond en vervangen de vorige graph niet.

## 6. Graph UI-contract (optioneel)

- Een aparte Graph Explorer toont Project/Document/Item/UnresolvedItem/ValidationFinding-nodes en alleen de ingestelde edge/statusfilters. De bestaande documentboom en editor blijven bereikbaar en behouden hun selectie-/editlogica.
- Node-activatie van Item selecteert het bestaande document en item via Python backend use-cases; Document-activatie selecteert het bestaande document. Graph nodes zelf zijn niet bewerkbaar.
- De gebruiker kan zoeken/filteren op competency-question-velden, de buurrelaties en impactrichting kiezen, en pannen/zoomen/selecteren met keyboard-accessible node focus. Selectie/filters zijn UI-state, geen Doorstopdata.
- Review, suspect, validation `unknown/stale/failed` moeten tekstueel worden aangegeven, niet alleen met kleur. Empty/loading/error states zijn expliciet.

## 7. V1-besluiten en niet-doelen

- Geen persisted graph state/cache, graph database, remote graph service, RDF/OWL/JSON-LD, standaardcomplianceclaim of semantische reasoner.
- Geen graph-edit acties, nieuwe Doorstop-rules, eigen watcher, nieuwe review-/suspect-stampregels of duplicated validation.
- Geen globale cross-project identiteit: één graph instance representeert één geopende projectroot.
- Geen automatische claim dat één seconde gehaald is tot event-to-model latency is gemeten en performance fixture/revisie is opgeslagen.
- Geen complianceclaim voor deze app-eigen vocabulary.

## 8. Validatieplan

1. Unit-tests voor IDs, alle relationele types, parent-doc direction, native item-link direction, inverse impact traversal, cycles, unresolved target, review stamp, per-link suspect status, finding association and provenance.
2. Regression tests: local item save/review/link mutation, restore and delete, plus existing watcher modify/add/delete/rebuild events replace graph snapshots; malformed-item load errors never surface stale attributes; stale validation results cannot become current; failed root-switch keeps the previous graph.
3. Qt integration tests: graph toggle/optional view, filters/search, selecting document/item navigates existing QML lists/editor, keyboard path and accessibility states.
4. Latency benchmark: generated on-disk Doorstop project with pinned Python/Qt, OS and revision; at least 2,500 items across document hierarchy with representative link density. Measure initial build, local-save-to-`graphChanged`, watcher-event-to-`graphChanged`, and validation projection separately; report median/p95/max and memory. Each controlled relation/status update must appear within ≤1s; report median, p95 and maximum, with validation timing reported separately.
5. Do not close `.9` until all three graph goals, live update target, large-project evidence and optional navigation workflow have evidence. Parent `.9` is currently dependency-blocked by open Beads `.2` and `.8`; this request starts `.9.1` and does not waive those blockers or imply overall QML parity.
