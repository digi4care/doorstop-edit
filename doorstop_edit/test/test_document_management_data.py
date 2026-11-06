import shutil
from pathlib import Path

import doorstop
import pytest
from doorstop import settings as doorstop_settings

from doorstop_edit.doorstop_data import DoorstopData
from tools.gen_sample_tree import generate_tree


def test_create_document_creates_and_rebuilds(tmp_path: Path) -> None:
    generate_tree(tmp_path, 1, 1)
    doorstop_data = DoorstopData(None, tmp_path)
    doorstop_data.rebuild(False)
    prefix = doorstop_data.create_document("NEW", parent="REQ-A")
    assert prefix == "NEW"
    assert doorstop_data.find_document("NEW") is not None
    assert (tmp_path / "NEW").is_dir()
    document = doorstop_data.find_document("NEW")
    assert document is not None
    assert str(document.parent) == "REQ-A"


def test_create_document_without_parent_is_top_level(tmp_path: Path) -> None:
    doorstop_data = DoorstopData(None, tmp_path)
    doorstop_data.rebuild(False)
    prefix = doorstop_data.create_document("TOP")
    assert prefix == "TOP"
    document = doorstop_data.find_document(prefix)
    assert document is not None
    assert document.parent is None


def test_create_document_validates_before_mutating(tmp_path: Path) -> None:
    generate_tree(tmp_path, 1, 1)
    doorstop_data = DoorstopData(None, tmp_path)
    doorstop_data.rebuild(False)
    invalid_prefixes = (
        "",
        "  ",
        " A",
        "A ",
        "A B",
        "a/b",
        "a\\b",
        ".",
        "..",
        "A:B",
        "A?B",
        "A*B",
        "A<B",
        "A>B",
        "A|B",
        'A"B',
        "A\x01B",
    )
    for prefix in invalid_prefixes:
        with pytest.raises(doorstop.DoorstopError):
            doorstop_data.create_document(prefix)
    assert not (tmp_path / "  ").exists()


def test_remove_document_refuses_documents_with_children(doorstop_data: DoorstopData) -> None:
    document = doorstop_data.find_document("REQ-A")
    assert document is not None and document.children
    with pytest.raises(doorstop.DoorstopError, match="child"):
        doorstop_data.remove_document(document.prefix)
    assert doorstop_data.find_document(document.prefix) is document


def test_remove_document_deletes_leaf_and_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doorstop_settings, "ADDREMOVE_FILES", False)
    generate_tree(tmp_path, 1, 1)
    doorstop_data = DoorstopData(None, tmp_path)
    doorstop_data.rebuild(False)
    prefix = doorstop_data.create_document("LEAF", parent="REQ-A")
    item_file = next((tmp_path / "REQ-A").glob("REQ-A-*.yml"))
    copied_item = tmp_path / prefix / item_file.name.replace("REQ-A", prefix)
    shutil.copy(item_file, copied_item)
    doorstop_data.rebuild(False)
    doorstop_data.remove_document(prefix)
    assert doorstop_data.find_document(prefix) is None
    assert not (tmp_path / prefix).exists()
    assert not copied_item.exists()


def test_remove_document_refuses_unmanaged_content_before_item_deletion(tmp_path: Path) -> None:
    generate_tree(tmp_path, 1, 1)
    doorstop_data = DoorstopData(None, tmp_path)
    doorstop_data.rebuild(False)
    prefix = doorstop_data.create_document("LEAF", parent="REQ-A")
    item_file = next((tmp_path / "REQ-A").glob("REQ-A-*.yml"))
    copied_item = tmp_path / prefix / item_file.name.replace("REQ-A", prefix)
    shutil.copy(item_file, copied_item)
    doorstop_data.rebuild(False)
    unmanaged = tmp_path / prefix / "keep.txt"
    unmanaged.write_text("keep", encoding="utf-8")

    with pytest.raises(doorstop.DoorstopError, match="unmanaged"):
        doorstop_data.remove_document(prefix)

    assert copied_item.exists()
    assert unmanaged.read_text(encoding="utf-8") == "keep"


def test_failed_root_rebuild_restores_active_watcher(tmp_path: Path) -> None:
    valid = tmp_path / "valid"
    invalid = tmp_path / "invalid"
    valid.mkdir()
    invalid.mkdir()
    generate_tree(valid, 1, 1)
    (invalid / ".doorstop.yml").write_text("settings: [invalid", encoding="utf-8")
    doorstop_data = DoorstopData(None, valid)
    doorstop_data.rebuild(False)
    old_tree = doorstop_data._tree
    doorstop_data.start()

    try:
        with pytest.raises(doorstop.DoorstopError):
            doorstop_data.rebuild(False, new_root=invalid)

        assert doorstop_data.root == valid
        assert doorstop_data._tree is old_tree
        assert doorstop_data.file_watcher._started
        assert doorstop_data.file_watcher.observer.is_alive()
        assert [Path(doc.path).resolve() for doc in doorstop_data.file_watcher.scheduled_docs] == [
            Path(doc.path).resolve() for doc in doorstop_data.get_documents().values()
        ]
    finally:
        doorstop_data.stop()
