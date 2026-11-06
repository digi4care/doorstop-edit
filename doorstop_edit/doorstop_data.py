import copy
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Generator, Iterable, List, Optional, Union

import doorstop
from doorstop import settings as doorstop_settings
from PySide6.QtCore import QObject, Signal, Slot

from doorstop_edit.utils.debug_timer import time_function
from doorstop_edit.utils.file_watcher import FileWatcher

logger = logging.getLogger("gui")
_WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class DocumentRemovalRefreshError(doorstop.DoorstopError):
    """Deletion was attempted, but the application could not reload the tree."""


@dataclass(frozen=True)
class ValidationFinding:
    severity: str
    message: str
    item_uid: Optional[str] = None


class _DocumentBoundary(doorstop.DoorstopInfo):
    """A hook marker that survives Doorstop's exception-type wrapping."""


class _ItemBoundary(doorstop.DoorstopInfo):
    """Distinguish item findings without guessing UIDs from message strings."""


def configure_validation_policy() -> None:
    """Set Doorstop's process-wide validation behavior before any worker starts."""
    # Doorstop 3.2 defaults to formatting and reviewing files during validation.
    # These are process globals: never change them temporarily in a worker thread.
    doorstop_settings.REFORMAT = False
    doorstop_settings.REVIEW_NEW_ITEMS = False
    doorstop_settings.REORDER = False


def collect_validation(root: Path) -> List[ValidationFinding]:
    """Validate a separate disk-backed tree, leaving the editor's live tree untouched.

    Doorstop 3.2 wraps each exception with a document/item label, but does not
    expose structured locations. Hook markers preserve the order and boundaries
    of built-in and extension findings, including document-only checks.
    """
    tree = doorstop.build(cwd=str(root), root=str(root))
    # Tree.load(reload=True) aborts at the first invalid item file, before
    # get_issues can report a finding. Item.uid comes from a validated filename.
    invalid_items: List[ValidationFinding] = []
    for document in tree:
        document.load()
        for item in document:
            try:
                item.load()
            except (doorstop.DoorstopError, ValueError, AttributeError) as exc:
                invalid_items.append(
                    ValidationFinding("error", f"Unable to load {item.itemformat.upper()} item: {exc}", str(item.uid))
                )

    if invalid_items:
        invalid_items.append(
            ValidationFinding(
                "info", "Other project validation checks were not run until invalid item files are fixed."
            )
        )
        return invalid_items

    items: Deque[str] = deque()

    def document_hook(*, document: doorstop.Document, tree: doorstop.Tree) -> List[doorstop.DoorstopInfo]:
        return [_DocumentBoundary("document boundary")]

    def item_hook(
        *, item: doorstop.Item, document: doorstop.Document, tree: doorstop.Tree
    ) -> List[doorstop.DoorstopInfo]:
        items.append(str(item.uid))
        return [_ItemBoundary("item boundary")]

    findings = []
    current_uid: Optional[str] = None
    for issue in tree.get_issues(document_hook=document_hook, item_hook=item_hook):
        if isinstance(issue, _DocumentBoundary):
            current_uid = None
            continue
        if isinstance(issue, _ItemBoundary):
            current_uid = items.popleft()
            continue
        if isinstance(issue, doorstop.DoorstopInfo):
            severity = "info"
        elif isinstance(issue, doorstop.DoorstopWarning):
            severity = "warning"
        else:
            severity = "error"
        findings.append(ValidationFinding(severity, str(issue), current_uid))
    return findings


class ItemMetadata:
    def __init__(self) -> None:
        self.original: Optional[str] = None
        self.last_change = 0


class DoorstopData(QObject):
    """Container holding all doorstop data (tree) for the whole application.

    It has accessors for easily getting and finding the data in a preferred form.

    The doorstop objects returned from this class should not be stored locally in a permanent way.
    The rule is: access the pieces that you need for the moment and access this class again when
    updates are needed. Object will be replaced when tree is reloaded and should therefore not be
    cached longterm since it can lead to saving old data, for example.
    """

    tree_changed = Signal((bool))  # Called when tree changed on disk
    item_saved = Signal()
    contentChanged = Signal(str, int, str)
    _fileWatchEvent = Signal(bool, object, int)

    def __init__(self, parent: Optional[QObject], root: Optional[Path] = None) -> None:
        super().__init__(parent=parent)
        self.root = root
        self._tree: Optional[doorstop.Tree] = None
        self.tree_stale = False
        self.content_revision = 0
        self.item_metadata: Dict[str, ItemMetadata] = {}
        self._item_load_errors: Dict[str, str] = {}
        self._fileWatchEvent.connect(self._process_filewatch_callback)
        self.file_watcher = FileWatcher(self._on_filewatch_callback)

    def has_root(self) -> bool:
        return self.root is not None

    def item_load_errors(self) -> Dict[str, str]:
        """Return a copy of current item load failures keyed by stable UID."""
        return dict(self._item_load_errors)

    def start(self) -> None:
        self.file_watcher.start()

    def stop(self) -> None:
        self.file_watcher.stop()

    def _on_filewatch_callback(self, modified_only: bool, paths: tuple[str, ...], generation: int) -> None:
        self._fileWatchEvent.emit(modified_only, paths, generation)

    @Slot(bool, object, int)
    def _process_filewatch_callback(self, modified_only: bool, paths: object, generation: int) -> None:
        if generation != self.file_watcher.generation or not isinstance(paths, tuple) or self.root is None:
            return
        root = self.root.resolve()
        active = tuple(path for source in paths if (path := Path(source).resolve()).is_relative_to(root))
        if not active:
            return
        do_rebuild = not modified_only
        content_paths = []
        if modified_only:
            for filename in active:
                if ".doorstop" in filename.name:
                    do_rebuild = True
                    continue
                item = self.find_item(filename.stem)
                if item is None:
                    do_rebuild = True
                    continue
                try:
                    item.load(reload=True)
                except (doorstop.DoorstopError, ValueError, AttributeError) as exc:
                    self._item_load_errors[str(item.uid)] = str(exc)
                    logger.warning("Unable to load %s: %s", item.uid, exc)
                else:
                    self._item_load_errors.pop(str(item.uid), None)
                content_paths.append(filename)
        if do_rebuild:
            self.rebuild(only_reload=modified_only, reason="watcher")
        else:
            self._publish_content_changed("external-edit")
            self.tree_changed.emit(True)

    @Slot(bool)
    @time_function("Rebuilding document tree")
    def rebuild(self, only_reload: bool = False, new_root: Optional[Path] = None, reason: str = "rebuild") -> None:
        full_rebuild = new_root is not None or self._tree is None or not only_reload
        if full_rebuild:
            candidate_root = new_root if new_root is not None else self.root
            previous_root = self.root
            previous_tree = self._tree
            previous_tree_stale = self.tree_stale
            previous_errors = self._item_load_errors
            previous_docs = list(self.file_watcher.scheduled_docs)
            self.file_watcher.pause()
            try:
                candidate_tree = doorstop.build(cwd=str(candidate_root), root=str(candidate_root))
                candidate_errors: Dict[str, str] = {}
                for document in candidate_tree:
                    document.load()
                    for item in document:
                        try:
                            item.load(reload=True)
                        except (doorstop.DoorstopError, ValueError, AttributeError) as exc:
                            candidate_errors[str(item.uid)] = str(exc)
                            logger.warning("Unable to load %s: %s", item.uid, exc)
                # Commit only after all project/document configuration loads succeed.
                self.root = candidate_root
                self._tree = candidate_tree
                self.tree_stale = False
                self._item_load_errors = candidate_errors
                self.file_watcher.watch(list(candidate_tree))
            except Exception:
                self.root = previous_root
                self._tree = previous_tree
                self.tree_stale = previous_tree_stale
                self._item_load_errors = previous_errors
                try:
                    self.file_watcher.watch(previous_docs)
                except Exception:
                    logger.exception("Could not restore previous watcher schedule after rebuild failure")
                    self.file_watcher.pause()
                    self.file_watcher.scheduled_docs = previous_docs
                    self.file_watcher.resume()
                raise
            logger.debug("Loaded %d documents", len(self._tree.documents))
            self.tree_changed.emit(only_reload)
            self._publish_content_changed(reason)
            return

        # Eagerly load valid items without letting one malformed item prevent
        # the project and its other items from opening.
        tree = self._tree
        assert tree is not None
        for document in tree:
            document.load()
            has_invalid_item = False
            for item in document:
                try:
                    item.load(reload=True)
                except (doorstop.DoorstopError, ValueError, AttributeError) as exc:
                    has_invalid_item = True
                    self._item_load_errors[str(item.uid)] = str(exc)
                    logger.warning("Unable to load %s: %s", item.uid, exc)
                else:
                    self._item_load_errors.pop(str(item.uid), None)
            if only_reload and not has_invalid_item:
                # Preserve Doorstop's document config reload on ordinary refreshes.
                document.load(reload=True)
        logger.debug("Loaded %d documents", len(tree.documents))

        self.file_watcher.watch(list(self.get_documents().values()))
        self.tree_changed.emit(only_reload)
        self._publish_content_changed(reason)

    def _publish_content_changed(self, reason: str) -> None:
        self.content_revision += 1
        self.contentChanged.emit(str(self.root or ""), self.content_revision, reason)

    def get_documents(self) -> Dict[str, doorstop.Document]:
        """Get all documents in doorstop tree.

        Return: A dict of {document_name: Document}
        """
        retval = {}
        for doc in self._tree or []:
            retval[doc.prefix] = doc
        return retval

    def find_document(self, name: str) -> Optional[doorstop.Document]:
        return self.get_documents().get(name, None)

    def create_document(self, prefix: str, parent: Optional[str] = None) -> str:
        """Create a safely named document under the project root and reload the tree."""
        if self.tree_stale:
            raise doorstop.DoorstopError("The document tree may be stale; reload the project before editing")
        if not isinstance(prefix, str) or not prefix or any(char.isspace() for char in prefix):
            raise doorstop.DoorstopError("Document prefix must not be blank or contain whitespace")
        if (
            prefix in (".", "..")
            or any(char in prefix for char in '/\\:*?"<>|')
            or any(ord(char) < 32 or ord(char) == 127 for char in prefix)
            or prefix.endswith(".")
            or prefix.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        ):
            raise doorstop.DoorstopError(f"Invalid document prefix: {prefix!r}")
        if self.root is None or self._tree is None:
            raise doorstop.DoorstopError("No project tree is loaded")
        if prefix in self.get_documents():
            raise doorstop.DoorstopError(f"Document prefix already exists: {prefix}")
        if parent is None and any(document.parent is None for document in self.get_documents().values()):
            raise doorstop.DoorstopError("A top-level document already exists; choose a parent document")
        if parent is not None and self.find_document(parent) is None:
            raise doorstop.DoorstopError(f"Unknown parent document: {parent}")
        target = self.root / prefix
        try:
            target.resolve().relative_to(self.root.resolve())
        except ValueError as exc:
            raise doorstop.DoorstopError(f"Document path escapes project root: {prefix}") from exc
        if target.exists():
            raise doorstop.DoorstopError(f"Document path already exists: {target}")
        try:
            document = self._tree.create_document(path=str(target), value=prefix, parent=parent)
            return str(document.prefix)
        finally:
            self.rebuild()

    def remove_document(self, prefix: str) -> None:
        """Delete a leaf document, refusing to delete unmanaged directory content."""
        if self.tree_stale:
            raise doorstop.DoorstopError("The document tree may be stale; reload the project before editing")
        document = self.find_document(prefix)
        if document is None:
            raise doorstop.DoorstopError(f"Unknown document: {prefix}")
        if document.children:
            raise doorstop.DoorstopError(f"Cannot remove document {prefix}; child documents exist")
        if self.root is None:
            raise doorstop.DoorstopError("No project root is loaded")
        path = Path(document.path)
        if path.is_symlink():
            raise doorstop.DoorstopError(f"Cannot remove document through symlink directory: {path}")
        project_root = self.root.resolve()
        document_root = path.resolve()
        try:
            document_root.relative_to(project_root)
        except ValueError as exc:
            raise doorstop.DoorstopError(f"Document directory is outside project root: {path}") from exc
        item_paths = {Path(item.path) for item in document}
        config_path = Path(document.config)
        if config_path.is_symlink():
            raise doorstop.DoorstopError(f"Cannot remove document with symlink config: {config_path}")
        config_resolved = config_path.resolve()
        try:
            config_resolved.relative_to(document_root)
        except ValueError as exc:
            raise doorstop.DoorstopError(f"Document config is outside its directory: {config_path}") from exc
        for item_path in item_paths:
            if item_path.is_symlink():
                raise doorstop.DoorstopError(f"Cannot remove document with symlink item: {item_path}")
            try:
                item_path.resolve().relative_to(document_root)
            except ValueError as exc:
                raise doorstop.DoorstopError(f"Document item is outside its directory: {item_path}") from exc
        entries = list(path.iterdir())
        symlinks = [entry for entry in entries if entry.is_symlink()]
        if symlinks:
            names = ", ".join(entry.name for entry in symlinks)
            raise doorstop.DoorstopError(f"Cannot remove document with symlink entries: {names}")
        item_paths_resolved = {item_path.resolve() for item_path in item_paths}
        unmanaged = [
            entry
            for entry in entries
            if entry.resolve() not in item_paths_resolved and entry.resolve() != config_resolved
        ]
        if unmanaged:
            names = ", ".join(entry.name for entry in unmanaged)
            raise doorstop.DoorstopError(f"Cannot remove document; unmanaged entries: {names}")
        mutation_attempted = True
        try:
            document.delete()
            if config_path.exists():
                config_path.unlink()
            if path.exists():
                path.rmdir()
        finally:
            if mutation_attempted:
                try:
                    self.rebuild()
                except Exception as exc:
                    self.tree_stale = True
                    raise DocumentRemovalRefreshError(
                        f"Deletion of {prefix} was attempted, but the document tree could not be refreshed: {exc}"
                    ) from exc

    def find_item(self, item_uid: str, document: Union[str, doorstop.Document, None] = None) -> Optional[doorstop.Item]:
        doc: Optional[doorstop.Document] = None
        if document is None:
            for i_doc_name, i_doc in self.get_documents().items():
                if i_doc_name in item_uid:
                    doc = i_doc
                    break
        elif isinstance(document, str):
            doc = self.find_document(document)
        else:
            doc = document

        if doc is None:
            return None

        for item in doc:
            if item_uid == item.uid:
                return item

        return None

    def iter_items(self, document: Optional[doorstop.Document] = None) -> Generator[doorstop.Item, None, None]:
        tree: Iterable[doorstop.Document]
        if document is None:
            tree = self._tree or []
        else:
            tree = [document]
        doc: doorstop.Document
        for doc in tree:
            for item in doc:
                yield item

    def save_item(self, item: doorstop.Item) -> None:
        """Save item to disk.

        This application must always call this instead of directly calling Item.save() to be able to
        restore the item later.
        """
        if self.tree_stale:
            raise ValueError(
                "The document tree may be stale after a failed deletion; reload the project before editing"
            )
        if self.get_item_load_error(str(item.uid)) is not None:
            raise ValueError(f"Cannot save invalid item {item.uid} until its file is valid")
        # Validate independently: loading into `item` would discard unsaved editor state.
        path = Path(item.path)
        if path.is_file():
            disk_item = copy.deepcopy(item)
            try:
                disk_item.load(reload=True)
            except (doorstop.DoorstopError, ValueError, AttributeError) as exc:
                uid = str(item.uid)
                self._item_load_errors[uid] = str(exc)
                logger.warning("Unable to load %s: %s", uid, exc)
                self.tree_changed.emit(True)
                raise ValueError(f"Cannot save invalid item {uid} until its file is valid") from exc
        self.file_watcher.pause()  # To not trigger file changes on editor changes.

        p = Path(item.path)
        if str(item.uid) not in self.item_metadata:
            self.item_metadata[str(item.uid)] = ItemMetadata()
            if p.is_file():
                self.item_metadata[str(item.uid)].original = p.read_text("utf-8")
            elif not p.is_file():
                # New file
                self.item_metadata[str(item.uid)].original = ""
        self.item_metadata[str(item.uid)].last_change = int(time.time())
        item.save()
        item.auto = False  # Turn off auto-save that is enabled when calling save().
        if self.item_metadata[str(item.uid)].original == Path(item.path).read_text("utf-8"):
            # If no change, set to None to indicate no change.
            self.item_metadata[str(item.uid)].original = None

        self.file_watcher.resume()
        self.item_saved.emit()
        self._publish_content_changed("save")

    def get_item_load_error(self, uid: str) -> Optional[str]:
        """Return the most recent load error for an item, if it is invalid."""
        return self._item_load_errors.get(uid)

    def get_original_data(self, item: doorstop.Item) -> Optional[str]:
        """None means no change."""
        if str(item.uid) in self.item_metadata:
            return self.item_metadata[str(item.uid)].original
        return None

    def has_item_changed(self, item: doorstop.Item) -> bool:
        """Returns True if item has changed on disk since application start."""
        return str(item.uid) in self.item_metadata and self.item_metadata[str(item.uid)].original is not None

    def restore_item(self, item: doorstop.Item) -> None:
        """Restore item to its original content on disk."""
        if str(item.uid.value) not in self.item_metadata:
            # Nothing to restore from.
            return

        orig = self.item_metadata[str(item.uid)].original
        if orig is None:
            return

        p = Path(item.path)
        self.file_watcher.pause()
        try:
            p.write_text(orig, encoding="utf-8")
            item.load(reload=True)  # Reload item to mirror content on disk.
        finally:
            self.file_watcher.resume()
        self.item_metadata[str(item.uid)].original = None
        self.item_saved.emit()
        self._publish_content_changed("restore")

    def delete_item(self, uid: str) -> None:
        """Delete an item inside the active project and refresh the document tree."""
        if self.tree_stale:
            raise doorstop.DoorstopError("The document tree may be stale; reload the project before editing")
        if self.root is None:
            raise doorstop.DoorstopError("No project root is loaded")
        item = self.find_item(uid)
        if item is None:
            raise doorstop.DoorstopError(f"Unknown item: {uid}")
        path = Path(item.path)
        if path.is_symlink():
            raise doorstop.DoorstopError(f"Cannot delete item through symlink: {path}")
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError as exc:
            raise doorstop.DoorstopError(f"Item path is outside project root: {path}") from exc

        item.delete()
        self.item_metadata.pop(str(item.uid), None)
        try:
            self.rebuild(only_reload=False, reason="delete")
        except Exception as exc:
            self.tree_stale = True
            raise doorstop.DoorstopError(
                f"Item {uid} was deleted, but the project tree could not be refreshed"
            ) from exc

    def get_last_change(self, item: doorstop.Item) -> int:
        """Get timestamp of items last change/save.

        Zero (0) means item has never been changed.
        """
        if str(item.uid.value) not in self.item_metadata:
            return 0
        return self.item_metadata[str(item.uid.value)].last_change
