# Document management

## Adding a document

Use **Add document** beside the document selector. Enter a Doorstop prefix and optionally choose a
parent document; **None — top-level** creates a root document. The current document is the initial
parent selection when one is available. Prefix input must not be silently normalized or interpreted
as a path: reject blank input, whitespace, path separators, dot segments, platform-invalid filename
characters/reserved names, an existing prefix, or an existing destination directory before creating
anything. The document directory is created under the project root through Doorstop. After a
successful create, rebuild the tree, refresh the document selector, and select the new document.
Doorstop permits only one top-level document: an empty project can create one, but a project with an
existing root must choose a parent rather than attempting a second root.

## Removing a document

**Remove document** applies only to the document selected in the document selector. If it has child
documents, refuse before confirmation or any destructive operation and list the children. Do not
delete, move, or reparent children implicitly. For a document without children, ask for explicit
confirmation before calling Doorstop's document deletion API. On success, rebuild the tree and
refresh the selector and editor state.

Doorstop 3.2 deletes a document's item files before attempting to remove its directory, and it does
not provide transactional rollback. The application must not claim that filesystem errors are rolled
back or that no changes occurred after a failed deletion. Before calling Doorstop, the application
refuses deletion if the document directory contains entries other than its config and known item
files; this prevents ordinary leftover files from causing a partial deletion. Non-document files are
never recursively deleted. No rename or move support is included, and this feature adds no runtime
dependencies.

The application also refuses deletion through symlinked document directories, config files, or entries,
and verifies that the directory, config, and item paths remain inside their expected project/document
boundaries. If deletion is attempted but the subsequent tree refresh fails, deletion may already have
changed the filesystem; the UI marks the displayed tree as potentially stale, blocks editing, and
requires reopening or reloading the project before editing.
