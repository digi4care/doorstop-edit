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


def test_create_second_top_level_document_refuses_before_creating_directory(tmp_path: Path) -> None:
    data = DoorstopData(None, tmp_path)
    data.rebuild(False)
    data.create_document("ROOT")
    destination = tmp_path / "SECOND"
    with pytest.raises(doorstop.DoorstopError, match="top-level"):
        data.create_document("SECOND")
    assert not destination.exists()


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


def test_remove_document_refuses_symlink_config_before_mutation(tmp_path: Path) -> None:
    data = DoorstopData(None, tmp_path)
    data.rebuild(False)
    prefix = data.create_document("LEAF")
    document = data.find_document(prefix)
    assert document is not None
    config = Path(document.config)
    external = tmp_path.parent / f"{tmp_path.name}-outside-config.yml"
    external.write_text("external: keep\n", encoding="utf-8")
    original_config = config.with_name("original-config.yml")
    config.rename(original_config)
    try:
        config.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable: {exc}")

    with pytest.raises(doorstop.DoorstopError, match="symlink config"):
        data.remove_document(prefix)

    assert external.read_text(encoding="utf-8") == "external: keep\n"
    assert config.is_symlink()
    assert original_config.exists()
    assert (tmp_path / prefix).is_dir()


def test_remove_document_refuses_symlink_document_directory(tmp_path: Path) -> None:
    data = DoorstopData(None, tmp_path)
    data.rebuild(False)
    prefix = data.create_document("LEAF")
    directory = tmp_path / prefix
    outside = tmp_path.parent / f"{tmp_path.name}-outside-document"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    shutil.rmtree(directory)
    try:
        directory.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable: {exc}")

    with pytest.raises(doorstop.DoorstopError, match="symlink directory"):
        data.remove_document(prefix)

    assert directory.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_remove_document_rebuild_failure_marks_tree_stale_after_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from doorstop_edit.doorstop_data import DocumentRemovalRefreshError

    data = DoorstopData(None, tmp_path)
    data.rebuild(False)
    prefix = data.create_document("LEAF")
    document_path = tmp_path / prefix

    def fail_rebuild(*_args: object, **_kwargs: object) -> None:
        raise doorstop.DoorstopError("simulated reload failure")

    monkeypatch.setattr(data, "rebuild", fail_rebuild)
    with pytest.raises(DocumentRemovalRefreshError, match="Deletion.*attempted") as error:
        data.remove_document(prefix)

    assert "simulated reload failure" in str(error.value)
    assert not document_path.exists()
    assert data.tree_stale
