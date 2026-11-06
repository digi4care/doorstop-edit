from unittest.mock import Mock

import pytest

from doorstop_edit.item_render.fragmented_markdown import FragmentedMarkdown
from doorstop_edit.item_render.render_worker import ItemRenderer, ProgressTracker


def test_fragmented_markdown_resolves_cross_fragment_references_and_resets() -> None:
    markdown = FragmentedMarkdown(base_dir=".")
    first = markdown.add_fragement("See [guide].")
    second = markdown.add_fragement("[guide]: https://example.test/guide")
    assert first is not None
    assert second is not None

    markdown.process_fragments()

    assert "https://example.test/guide" in markdown.render_fragment(first)
    markdown.reset()
    assert markdown.num_fragments == 0
    assert len(markdown.fragments) == 0
    assert markdown.add_fragement("\n\t") is None


def test_item_renderer_forces_full_rerender_when_references_change(monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = ItemRenderer(Mock())
    item = Mock()
    item.uid.value = "REQ-1"
    renderer.cache[item.uid.value] = 1
    renderer.prev_refs[item.uid.value] = ["old"]
    prepare = Mock(side_effect=[([], ["new"]), ([], ["new"])])
    monkeypatch.setattr(ItemRenderer, "_prepare", staticmethod(prepare))
    monkeypatch.setattr(ItemRenderer, "_render_item", staticmethod(lambda md, item, rows: "rendered"))
    monkeypatch.setattr("doorstop_edit.item_render.render_worker.FragmentedMarkdown", Mock())

    list(renderer.process("root", partial=True, items=[(item, 2)]))

    assert prepare.call_count == 2
    assert renderer.cache[item.uid.value] == 2
    assert renderer.progress is not None
    assert renderer.progress.get() == 150


def test_progress_tracker_empty_and_completion() -> None:
    tracker = ProgressTracker(0)
    assert tracker.get() == 100
    tracker = ProgressTracker(2)
    assert tracker.progress_one() is True
    assert tracker.progress_one() is True
    assert tracker.get() == 100
