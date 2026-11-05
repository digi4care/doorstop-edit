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

    def __init__(self, parent: Optional[QObject], root: Optional[Path] = None) -> None:
        super().__init__(parent=parent)
        self.root = root
        self._tree: Optional[doorstop.Tree] = None
        self.item_metadata: Dict[str, ItemMetadata] = {}
        self.item_load_errors: Dict[str, str] = {}
        self.file_watcher = FileWatcher(self._on_filewatch_callback)

    def has_root(self) -> bool:
        return self.root is not None

    def start(self) -> None:
        self.file_watcher.start()

    def stop(self) -> None:
        self.file_watcher.stop()

    def _on_filewatch_callback(self, modified_only: bool, filename: str) -> None:
        do_rebuild = False
        if modified_only:
            item = self.find_item(Path(filename).stem)
            if item is None:
                do_rebuild = True
            else:
                try:
                    item.load(reload=True)
                except (doorstop.DoorstopError, ValueError, AttributeError) as exc:
                    # Keep the tree available so validation can show this item.
                    self.item_load_errors[str(item.uid)] = str(exc)
                    logger.warning("Unable to load %s: %s", item.uid, exc)
                else:
                    self.item_load_errors.pop(str(item.uid), None)
                self.tree_changed.emit(True)

        if ".doorstop" in filename:
            do_rebuild = True

        if not modified_only or do_rebuild:
            self.rebuild(only_reload=modified_only)

    @Slot(bool)
    @time_function("Rebuilding document tree")
    def rebuild(self, only_reload: bool = False, new_root: Optional[Path] = None) -> None:
        full_rebuild = new_root is not None or self._tree is None or not only_reload
        if full_rebuild:
            candidate_root = new_root if new_root is not None else self.root
            previous_root = self.root
            previous_tree = self._tree
            previous_errors = self.item_load_errors
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
                self.item_load_errors = candidate_errors
                self.file_watcher.watch(list(candidate_tree))
            except Exception:
                self.root = previous_root
                self._tree = previous_tree
                self.item_load_errors = previous_errors
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
                    self.item_load_errors[str(item.uid)] = str(exc)
                    logger.warning("Unable to load %s: %s", item.uid, exc)
                else:
                    self.item_load_errors.pop(str(item.uid), None)
            if only_reload and not has_invalid_item:
                # Preserve Doorstop's document config reload on ordinary refreshes.
                document.load(reload=True)
        logger.debug("Loaded %d documents", len(tree.documents))

        self.file_watcher.watch(list(self.get_documents().values()))
        self.tree_changed.emit(only_reload)

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
                self.item_load_errors[uid] = str(exc)
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

    def get_item_load_error(self, uid: str) -> Optional[str]:
        """Return the most recent load error for an item, if it is invalid."""
        return self.item_load_errors.get(uid)

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
        p.write_text(orig, encoding="utf-8")
        item.load(reload=True)  # Reload item to mirror content on disk.
        self.item_metadata[str(item.uid)].original = None

    def get_last_change(self, item: doorstop.Item) -> int:
        """Get timestamp of items last change/save.

        Zero (0) means item has never been changed.
        """
        if str(item.uid.value) not in self.item_metadata:
            return 0
        return self.item_metadata[str(item.uid.value)].last_change
