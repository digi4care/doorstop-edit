import shutil
from pathlib import Path

import doorstop
from pytestqt.qtbot import QtBot

from doorstop_edit.doorstop_data import DoorstopData
from tools.gen_sample_tree import generate_tree


def test_external_item_save_reloads_data_within_one_second(tmp_path: Path, qtbot: QtBot) -> None:
    generate_tree(tmp_path, 1, 2)
    data = DoorstopData(None, tmp_path)
    data.rebuild()
    data.start()
    try:
        external_tree = doorstop.build(cwd=str(tmp_path), root=str(tmp_path))
        external_tree.load(reload=True)
        external_item = external_tree.find_item("REQ-A-001")
        external_item.text = "Changed outside Doorstop Edit"

        with qtbot.wait_signal(data.tree_changed, timeout=1000):
            external_item.save()

        item = data.find_item("REQ-A-001")
        assert item is not None
        assert item.text == "Changed outside Doorstop Edit"
    finally:
        data.stop()


def test_external_item_deletion_removes_it_after_rebuild(tmp_path: Path, qtbot: QtBot) -> None:
    generate_tree(tmp_path, 1, 2)
    data = DoorstopData(None, tmp_path)
    data.rebuild()
    data.start()
    try:
        item = data.find_item("REQ-A-001")
        assert item is not None
        item_path = Path(item.path)

        with qtbot.wait_signal(data.tree_changed, timeout=1000):
            item_path.unlink()

        assert data.find_item("REQ-A-001") is None
    finally:
        data.stop()


def test_rebuild_after_project_root_was_removed_does_not_crash(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    generate_tree(root, 1, 2)
    data = DoorstopData(None, root)
    data.rebuild()

    shutil.rmtree(root)
    data.rebuild()

    assert data.get_documents() == {}


def test_watcher_ignores_paths_outside_project_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    generate_tree(root, 1, 2)
    data = DoorstopData(None, root)
    data.rebuild()
    generation = data.file_watcher.generation
    revision = data.content_revision

    data._process_filewatch_callback(True, (str((tmp_path / "outside.yml").resolve()),), generation)

    assert data.content_revision == revision
    data.stop()
