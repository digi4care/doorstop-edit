import logging
import re
import tempfile
from pathlib import Path
from typing import Callable, Dict, Generator, List, Optional, Tuple, Union

import doorstop
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QObject,
    QThread,
    QWaitCondition,
    Signal,
)

from doorstop_edit import crash_log
from doorstop_edit.item_render.fragmented_markdown import Element, FragmentedMarkdown
from doorstop_edit.utils import item_utils
from doorstop_edit.utils.debug_timer import time_function

logger = logging.getLogger("gui")

QUEUE_DATA_TYPE = 0
QUEUE_PROGRESS_TYPE = 1


class ProgressTracker:
    def __init__(self, total: int) -> None:
        self.total_count = total
        self.count = 0
        self.report_interval = max(int(self.total_count / 100), 1)

    def progress_one(self) -> bool:
        """Return True if enough to report"""
        if self.count <= self.total_count:
            self.count += 1
        return self.count % self.report_interval == 0

    def get(self) -> int:
        """Returns percetage to completion."""
        if self.total_count == 0:
            return 100
        return round(((self.count) / self.total_count) * 100)


class ItemRenderer:
    def __init__(self, progress_cb: Callable[[int], None], error_cb: Optional[Callable[[str], None]] = None) -> None:
        self.progress_cb = progress_cb
        self.error_cb = error_cb
        self.progress: Optional[ProgressTracker] = None
        self.md: Optional[FragmentedMarkdown] = None
        self.cache: Dict[str, int] = {}
        self.prev_refs: Dict[str, List[str]] = {}
        self.current_root = ""

    def process(
        self, root: str, partial: bool, items: List[Tuple[doorstop.Item, int]]
    ) -> Generator[Tuple[str, str], None, None]:
        try:
            if not self.md or root != self.current_root:
                self.md = FragmentedMarkdown(base_dir=root)

            if not partial:
                self._reset_state()

            self.progress = ProgressTracker(len(items) * 2)
            prepared_items: List[Optional[List[Tuple[str, Union[str, Element]]]]] = []
            for item, ts in items:
                if partial and item.uid.value in self.cache and self.cache[item.uid.value] == ts:
                    prepared_items.append(None)
                else:
                    rows, refs = self._prepare(self.md, item)
                    if item.uid.value in self.prev_refs and self.prev_refs[item.uid.value] != refs:
                        # References has changed, rerender all from start...
                        self.prev_refs = {}
                        self.cache = {}
                        self.md.reset()
                        yield from self.process(root=root, partial=False, items=items)
                        return
                    prepared_items.append(rows)
                    self.prev_refs[item.uid.value] = refs

                if self.progress.progress_one():
                    self.progress_cb(self.progress.get())

            self.md.process_fragments()

            for i, (item, ts) in enumerate(items):
                item_rows = prepared_items[i]
                if item_rows is not None:
                    content = self._render_item(self.md, item, item_rows)
                    yield (item.uid.value, content)
                    self.cache[item.uid.value] = ts
                if self.progress.progress_one():
                    self.progress_cb(self.progress.get())

            if not partial:
                yield ("footer", self.md.render_footer())

            self.progress.progress_one()
            self.progress_cb(self.progress.get())
        except Exception as e:
            logger.error("Failed to process markdown: %s", e)
            if self.error_cb is not None:
                self.error_cb(str(e))

    def _reset_state(self) -> None:
        self.prev_refs = {}
        self.cache = {}
        if self.md:
            self.md.reset()

    @staticmethod
    def _render_item(md: FragmentedMarkdown, item: doorstop.Item, attrs: List[Tuple[str, Union[str, Element]]]) -> str:
        if item_utils.is_header_item(item):
            levels = str(item.level).count(".")
            header_tag = f"h{levels}"
            header = ""
            text_lines = item.text.splitlines()
            if len(text_lines) > 0:
                header = text_lines[0]
        else:
            header_tag = "p"
            header = item.header

        html = f"<{header_tag}><b>{str(item.level)} {header}</b> <small>{item.uid.value}</small></{header_tag}>"

        html += '<table class="req-table">'
        for attr, val in attrs:
            if len(val) == 0:
                continue
            html += '<tr class="req-table">'
            colspan = 2
            if attr != "text":
                html += f'<th class="req-table">{attr.capitalize()}</th>'
                colspan = 1
            if not isinstance(val, str):
                val = md.render_fragment(val)
            html += f'<td colspan="{colspan}">{val}</td>'
            html += "</tr>"
        html += "</table>"

        return html

    @staticmethod
    def _prepare(
        md: FragmentedMarkdown, item: doorstop.Item
    ) -> Tuple[List[Tuple[str, Union[str, Element]]], List[str]]:
        refs = []

        def add_fragement_proxy(text: str) -> Optional[Element]:
            refs.extend(re.findall(r"^\s*\[(.*)\]:\s(.*)$", text, flags=re.MULTILINE))
            return md.add_fragement(text)

        rows: List[Tuple[str, Union[str, Element]]] = []
        if item_utils.is_header_item(item):
            item_text = "\n".join(item.text.splitlines()[1:])
        else:
            item_text = item.text
        text_fragment = add_fragement_proxy(item_text)
        rows.append(("text", "" if text_fragment is None else text_fragment))
        if item.document and item.document.publish:
            for attr in item.document.publish:
                if attr in [row[0] for row in rows]:
                    continue
                val = item.attribute(attr)
                if val is None:
                    continue
                if isinstance(val, str) and len(val) > 0:
                    fragment = add_fragement_proxy(val)
                    rows.append((attr, "" if fragment is None else fragment))
                elif isinstance(val, bool):
                    rows.append((attr, str(val)))

        parent_links = []
        for link_item in item.parent_items:
            if not isinstance(link_item, doorstop.Item):
                continue
            parent_links.append(
                f'<a href="#" onclick="open_item(event, \'{link_item.uid.value}\')">'
                f"{link_item.uid.value} {link_item.header}</a>"
            )
        rows.append(("parents", ", ".join(parent_links)))

        child_links = []
        for link_item in item.find_child_items():
            if not isinstance(link_item, doorstop.Item):
                continue
            child_links.append(
                f'<a href="#" onclick="open_item(event, \'{link_item.uid.value}\')">'
                f"{link_item.uid.value} {link_item.header}</a>"
            )
        rows.append(("children", ", ".join(child_links)))

        return (rows, refs)


class RenderWorker(QThread):
    """Concurrent worker for generating HTML from markdown."""

    # Widgets API: batch generation is supplied by the caller.
    result_ready = Signal(str, str, int, name="result_ready")
    batch_finished = Signal(int, name="batch_finished")
    # QML API: request IDs are allocated by render() and tag every signal.
    progress = Signal(int, name="progress")
    error = Signal(str, name="error")
    result_tagged = Signal(int, str, str)
    progress_tagged = Signal(int, int)
    error_tagged = Signal(int, str)
    finished_tagged = Signal(int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.plantuml_cache = tempfile.gettempdir()
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self.abort = False
        self.change = 0
        self.restart = False
        self.items: List[Tuple[doorstop.Item, int]] = []
        self.root: Path = Path()
        self.generation = 0

    def destroy(self) -> None:
        crash_log.record("render.destroy.begin")
        with QMutexLocker(self.mutex):
            self.abort = True
            self.condition.wakeOne()
        self.wait()
        crash_log.record("render.destroy.end")

    @time_function("render")
    def render(
        self, items: List[Tuple[doorstop.Item, int]], root: Path, partial: bool, generation: Optional[int] = None
    ) -> int:
        """Queue a render; optional generation is the Widgets batch identifier."""
        with QMutexLocker(self.mutex):
            self.items = items
            self.root = root
            self.partial = partial
            self.change += 1
            request = self.change
            self.generation = request if generation is None else generation
            self.restart = True
            self.condition.wakeOne()
        crash_log.record("render.request", change=request, item_count=len(items), partial=partial)
        if not self.isRunning():
            self.start(QThread.Priority.NormalPriority)
        return request

    def _on_progress(self, p: int) -> None:
        self.progress.emit(p)

    def _is_current(self, request: int) -> bool:
        with QMutexLocker(self.mutex):
            return not self.abort and self.change == request

    def _abort_requested(self) -> bool:
        return self.abort

    def run(self) -> None:
        crash_log.record("render.worker.start")
        item_renderer = ItemRenderer(self._on_progress)
        last_change = 0
        while True:
            with QMutexLocker(self.mutex) as qm:
                if self._abort_requested():
                    crash_log.record("render.worker.stop", reason="abort")
                    return
                if self.change == last_change:
                    self.condition.wait(qm.mutex())
                if self._abort_requested():
                    return
                last_change = self.change
                request = last_change
                generation = self.generation
                items = self.items.copy()
                partial = self.partial
                root = Path(self.root)

            def report_progress(p: int) -> None:
                if self._is_current(request):
                    self.progress.emit(p)
                    self.progress_tagged.emit(request, p)

            def report_error(detail: str) -> None:
                if self._is_current(request):
                    self.error.emit(detail)
                    self.error_tagged.emit(request, detail)

            item_renderer.progress_cb = report_progress
            item_renderer.error_cb = report_error
            for uid, content in item_renderer.process(root=str(root), partial=partial, items=items):
                if not self._is_current(request):
                    break
                self.result_ready.emit(uid, content, generation)
                self.result_tagged.emit(request, uid, content)
            # A superseded batch is not complete for either consumer. Its replacement
            # emits both completion signals once its own results have been delivered.
            if self._is_current(request):
                self.batch_finished.emit(generation)
                self.finished_tagged.emit(request)
