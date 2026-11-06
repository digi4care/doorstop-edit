"""Reproducible benchmark for the QML application knowledge-graph projection."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, cast

from PySide6 import QtCore, QtWidgets

from doorstop_edit.doorstop_data import DoorstopData
from doorstop_edit.qml_backend import QmlBackend
from tools.gen_sample_tree import generate_tree


def percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "median_seconds": statistics.median(values),
        "p95_seconds": percentile95(values),
        "max_seconds": max(values),
    }


def await_graph(
    backend: QmlBackend, operation: Callable[[], None], expected_nodes: int, expected_revision: int
) -> float:
    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    observed: list[tuple[float, int, int]] = []

    def changed() -> None:
        graph = cast(dict[str, object], backend.appGraph)
        nodes = cast(list[object], graph.get("nodes", []))
        revision = cast(int, graph.get("contentRevision", -1))
        observed.append((time.perf_counter(), len(nodes), revision))
        loop.quit()

    backend.graphChanged.connect(changed)
    start = time.perf_counter()
    operation()
    timer.timeout.connect(loop.quit)
    timer.start(30000)
    loop.exec()
    backend.graphChanged.disconnect(changed)
    if not observed:
        raise RuntimeError("Timed out waiting for graphChanged")
    if observed[0][2] != expected_revision:
        raise RuntimeError(f"Visible content revision inconsistent: {observed[0][2]} != {expected_revision}")
    if observed[0][1] != expected_nodes:
        raise RuntimeError(f"Graph node count inconsistent: {observed[0][1]} != {expected_nodes}")
    return observed[0][0] - start


def measure_heartbeat_stall(backend: QmlBackend) -> dict[str, float | int | str]:
    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.setInterval(10)
    ticks: list[float] = []
    publication_elapsed: list[float] = []
    published = False

    def heartbeat() -> None:
        nonlocal published
        now = time.perf_counter()
        ticks.append(now)
        if len(ticks) == 3 and not published:
            published = True

            def publish() -> None:
                start = time.perf_counter()
                backend._publish_graph("heartbeat-probe", backend._data.content_revision)
                publication_elapsed.append(time.perf_counter() - start)
                QtCore.QTimer.singleShot(60, loop.quit)

            QtCore.QTimer.singleShot(0, publish)

    timer.timeout.connect(heartbeat)
    timer.start()
    loop.exec()
    timer.stop()
    timer.timeout.disconnect(heartbeat)
    gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:])]
    if len(ticks) < 3 or not publication_elapsed:
        raise RuntimeError("Heartbeat probe did not complete")
    return {
        "timer_interval_ms": 10,
        "tick_count": len(ticks),
        "maximum_inter_tick_gap_seconds": max(gaps),
        "graph_publication_elapsed_seconds": publication_elapsed[0],
        "interpretation": (
            "Python/Qt event-loop stall proxy during synchronous graph projection; not rendered-frame jank"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--items-per-document", type=int, default=834)
    args = parser.parse_args()
    if args.samples < 1 or args.items_per_document < 1:
        parser.error("samples and items-per-document must be positive")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    del app
    backend: QmlBackend | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="doorstop-kg-benchmark-") as directory:
            root = Path(directory)
            generate_tree(root, num_docs=3, num_req=args.items_per_document)
            baseline_data = DoorstopData(None, root)
            started = time.perf_counter()
            baseline_data.rebuild(False)
            doorstop_baseline_seconds = time.perf_counter() - started
            baseline_data.stop()

            started = time.perf_counter()
            backend = QmlBackend(root=root)
            initial_seconds = time.perf_counter() - started
            approximate_delta = initial_seconds - doorstop_baseline_seconds

            heartbeat_result = measure_heartbeat_stall(backend)
            expected_nodes = 4 + 3 * args.items_per_document
            actual_nodes = len(cast(dict[str, list[object]], backend.appGraph).get("nodes", []))
            if actual_nodes != expected_nodes:
                raise RuntimeError(f"Initial node count inconsistent: {actual_nodes} != {expected_nodes}")
            local: list[float] = []
            external: list[float] = []
            item_path = root / "REQ-A" / "REQ-A-001.yml"
            local_item = backend._data.find_item("REQ-A-001")
            if local_item is None:
                raise RuntimeError("Unable to load local benchmark item")
            for index in range(args.samples):
                header = f"Local benchmark update {index}"

                def save_local(value: str = header) -> None:
                    item = backend._data.find_item("REQ-A-001")
                    if item is None:
                        raise RuntimeError("Benchmark item disappeared")
                    item.header = value
                    item.text = value
                    backend._data.save_item(item)

                expected_revision = backend._data.content_revision + 1
                local.append(await_graph(backend, save_local, expected_nodes, expected_revision))

                def write_external(i: int = index) -> None:
                    contents = item_path.read_text(encoding="utf-8")
                    item_path.write_text(contents + f"\n# external benchmark update {i}\n", encoding="utf-8")

                expected_revision = backend._data.content_revision + 1
                external.append(await_graph(backend, write_external, expected_nodes, expected_revision))
            rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_unit = "bytes" if sys.platform == "darwin" else "KiB"
            peak_rss_bytes = rss_raw if sys.platform == "darwin" else rss_raw * 1024
            within = all(value <= 1.0 for value in [*local, *external])
            print(
                json.dumps(
                    {
                        "project": {
                            "documents": 3,
                            "items_per_document": args.items_per_document,
                            "items": 3 * args.items_per_document,
                            "nodes": expected_nodes,
                            "representative_links": True,
                        },
                        "samples_per_update_type": args.samples,
                        "expected_content_revision_at_each_signal": "previous revision + 1",
                        "doorstop_only_rebuild_seconds": doorstop_baseline_seconds,
                        "graph_enabled_backend_open_seconds": initial_seconds,
                        "approximate_graph_enabled_minus_doorstop_seconds": approximate_delta,
                        "baseline_comparison_note": (
                            "Sequential measurements on the same fixture; cold-warm/cache effects "
                            "mean the delta is not causal isolation."
                        ),
                        "event_loop_heartbeat_probe": heartbeat_result,
                        "initial_projection_build_seconds": initial_seconds,
                        "local_save_to_graphChanged": summarize(local),
                        "external_write_to_watcher_graphChanged": summarize(external),
                        "data_visibility": (
                            "Project root and up to 500 characters of item text are present in memory "
                            "exposed to QML; this benchmark introduces no graph persistence or export."
                        ),
                        "memory": {
                            "metric": "process_peak_rss",
                            "peak_rss_bytes": peak_rss_bytes,
                            "resource_ru_maxrss_raw": rss_raw,
                            "resource_ru_maxrss_unit": rss_unit,
                            "platform_unit_note": "ru_maxrss is bytes on macOS and KiB on Linux/other Unix",
                        },
                        "environment": {
                            "python": sys.version,
                            "qt": QtCore.qVersion(),
                            "pyside": __import__("PySide6").__version__,
                            "platform": platform.platform(),
                            "python_executable": sys.executable,
                            "cpu_count": os.cpu_count(),
                        },
                        "all_controlled_updates_within_1s": within,
                    },
                    indent=2,
                )
            )
            return 0 if within else 1
    finally:
        if backend is not None:
            backend.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
