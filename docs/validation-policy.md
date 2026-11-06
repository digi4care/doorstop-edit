# Validation trigger policy

## Decision

MVP 3 runs whole-project Doorstop validation:

- after the project has opened and its tree has loaded;
- after each successful item save; and
- when the user explicitly requests validation.

Item edits are automatically saved after 700 ms without further typing. Validation runs after that
save completes, not on every keystroke. The explicit action lets users request a fresh whole-project
check without making another edit.

Validation runs in a helper process so it does not block editing; large-project duration has not been
measured. Requests that arrive while a run is active coalesce into one rerun. Content revisions and
project roots are checked before results are displayed, so results from an older edit or a previous
project are ignored. External file changes update the revision and request a fresh check; this policy
does not claim a fixed upper bound for detecting or validating those changes.

## MVP 3 feedback

Validation runs against a separate disk-backed tree in a helper process, so editing remains available
and an unresponsive custom validator cannot block application shutdown indefinitely. Checks trigger
after tree loading, after a successful save, and through **File → Validate project**. While a check is
running, further requests coalesce into one new check; superseded results are not shown. Opening a
different project clears the previous project's item markers immediately.
The status bar shows error, warning, and notice counts and opens a full findings list when clicked.
Item entries use a visible symbol (✕ error, ⚠ warning, ℹ notice) and a tooltip with their messages;
document-level and project-level findings appear in the full list without an item marker.

Doorstop 3.2's `Tree.get_issues()` returns exception instances with no structured item location.
The validation helper configures Doorstop's process-wide `REFORMAT`, `REVIEW_NEW_ITEMS`, and
`REORDER` flags to `False` in the helper process before building the validation tree. Built-in
validation must not reformat files, review new items, or reorder levels. Project-provided custom
Python validators are arbitrary code and are **not sandboxed**; they may have side effects. On
application shutdown the app sends a force-kill to the helper and waits for at most 500 ms; any side
effects already performed by a custom validator cannot be undone. Processes spawned by a validator
are not guaranteed to be stopped. If the wait expires and the app exits before the daemon reaper can
remove the helper's private temporary result directory, that directory may remain in the system temp
directory; this does not delay shutdown.
There is no runtime timeout: a hung validator occupies the active validation indefinitely, and later
validation requests coalesce behind it and cannot run until the application closes (which terminates
the helper using the bounded shutdown procedure above).
Document and item hooks record boundaries while the generator yields, so built-in and extension item
findings can be associated with the item being checked. Document-wide checks, including skipped and
duplicate levels, remain unassociated rather than guessing an item from their text. A failed check
reports the failure in the status/list and keeps the last successful tree markers until a new check
completes. Validation findings never prevent saving or editing.

Malformed item YAML fails during Doorstop's item load, before `get_issues()` can yield findings. The
app loads each item separately and maps load errors only through the UID derived by Doorstop from a
valid item filename, not by parsing an error message. These items remain visible as error rows in the
tree. If any item cannot load, the checker lists all item load errors but **does not run the remaining
whole-project checks**: they may depend on the invalid item's missing data. It reports this incomplete
check as a project notice. An unreadable document configuration still fails at project level.
