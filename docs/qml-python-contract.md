# QML–Python contract: current implementation

This contract describes the first QML integration slice; it is not a claim of full Widgets parity. `QmlBackend` is the QObject façade. `DoorstopData` and its Doorstop tree remain the data owner and source of truth.

## Ownership and thread rules

- Construct `QmlBackend` and `DoorstopData` on the Qt GUI thread. All project rebuilds, item loads/saves, selections, and graph projection run on that thread. QML calls typed `Slot`s; it does not mutate Doorstop objects or duplicate business rules.
- `FileWatcher`/watchdog callbacks may originate off-thread. They emit `DoorstopData._fileWatchEvent`; its receiving slot `_process_filewatch_callback` performs path/generation checks and the Doorstop reload/rebuild on the QObject's owning Qt thread. Do not call Doorstop tree methods directly from a watcher callback.
- `ValidationService` runs the validator as a subprocess and polls it with a GUI-thread `QTimer`; it sends value-only `ValidationRunResult`s over a Qt signal. The result carries resolved root/project identity, input content revision, run ID, findings, state, timestamps, and optional error. Do not pass a Doorstop object or mutable tree to the worker/process.
- `QmlBackend.shutdown()` stops validation work and the existing watcher before the QML engine is disposed. Shutdown is idempotent at the service boundary; timed-out process reaping does not touch the Doorstop tree.

## Exposed properties and notifications

| QML property | Shape | Notification | Meaning |
|---|---|---|---|
| `projectRoot` | string | `projectRootChanged` | Current resolved/open project root, or empty. |
| `statusMessage` | string | `statusMessageChanged` | User-facing operation status. |
| `errorMessage` | string | `errorMessageChanged` | Last project/selection/save error, or empty. |
| `documents` | list of value maps | `documentsChanged` | `prefix`, `path`, `parent`, and item `count`. |
| `items` | list of value maps | `itemsChanged` | Selected document's `uid`, `level`, `header`, `active`, `normative`. |
| `selectedItem` | value map | `selectedItemChanged` | Current `uid`, `level`, `header`, and editable `text`. |
| `appGraph` | primitive value map | `graphChanged` | Current in-memory graph snapshot, content revision, graph generation and validation status. |

These are property snapshots, not a `QAbstractItemModel` role API. QML treats them as read-only and invokes commands for mutation. Notifications indicate that clients should fetch the property again.

## Commands and async/error behavior

- `openProjectPicker()` and `openProject(path)` load a project; invalid paths/configuration preserve the previous valid project and set `errorMessage`.
- `selectDocument(prefix)` and `selectItem(uid)` update the selected values and notify relevant properties. Selection errors are reported through `errorMessage`; no Doorstop reference is returned to QML.
- `saveSelected(header, text)` writes through `DoorstopData.save_item`, then updates the selected snapshot and status/error signals. Successful mutations publish normalized content revisions and graph snapshots.
- `shutdown()` tears down the service and watcher.
- `ValidationService.request(root, revision)` coalesces pending work to the latest request. It emits `running`, then `succeeded` or `failed`. The backend accepts a result only when root, project identity, and input revision match the current project state. Old-root/revision results are ignored. Prior findings remain stale during a new run or on failure; errors stay visible in the graph run status.
- Graph publication increments `graphGeneration`; only accepted Doorstop content changes increment `contentRevision`. A validation result cannot make old content current.

## Evidence and boundaries

QML/backend tests cover typed properties and selection/save, project-switch rollback, external updates, validation request coalescing/result identity and failure state, shutdown, and watcher callback dispatch. The watcher shares one observer at a time; it is stopped/joined and replaced between watch periods to discard queued stale events. This contract covers the graph/QML integration currently delivered, not all future frontend commands, complete Widgets parity, or cross-platform packaging.
