"""
Test Suite: Item Editor Dirty State for QML
Bead: doorstop-edit-qml-frontend-migration-plan-lml.2.3
Slice 3: Item Editor Component

TDD Approach: Tests written BEFORE full implementation
Goal: Verify ItemEditorModel dirty state tracking works correctly
Acceptance Criteria:
* currentItemData property werkt
* isDirty notify emit
* getUid() returns string
* saveItem emits signal
"""

import sys
from pathlib import Path

import pytest


def test_item_dirty_tracking_works() -> None:
    """
    TEST: test_item_dirty_tracking_works

    Verifies: ItemEditorModel dirty state tracking works as expected
    Metric: isDirty property changes and emits signal

    Acceptance: * currentItemData property werkt ✓
                * isDirty notify emit ✓
                * getUid() returns string ✓
    """

    sys.path.insert(0, str(Path(__file__).parent / ".." / "doorstop_edit"))

    from ui.qml_components import ItemEditorModel

    # Create test item data
    test_item = {
        "id": "REQ-001",
        "uid": "REQ-001",
        "title": "Login Functionality",
        "description": "User must be able to login",
        "status": "active",
        "priority": "high",
    }

    # Create model instance
    model = ItemEditorModel()
    model.loadItem(test_item)

    # Test 1: Verify initial state is not dirty
    assert not model.isDirty, "Item should not be dirty when first loaded"
    print("✓ Initial state is clean (not dirty)")

    # Test 2: Test currentItemData property
    current_data = model.getCurrentItemData()
    assert current_data["id"] == "REQ-001", f"Expected ID 'REQ-001', got {current_data['id']}"
    assert current_data["title"] == "Login Functionality", (
        f"Expected title 'Login Functionality', got {current_data['title']}"
    )
    print("✓ currentItemData property works correctly")

    # Test 3: Test getUid() method
    uid = model.getUid()
    assert uid == "REQ-001", f"Expected UID 'REQ-001', got {uid}"
    assert isinstance(uid, str), f"getUid() should return string, got {type(uid)}"
    print("✓ getUid() returns correct string value")

    # Test 4: Setup signal tracking BEFORE making changes
    signal_received = []
    model.dirty_state_changed.connect(lambda is_dirty: signal_received.append(is_dirty))

    # Make a field change - should emit signal
    model.setFieldValue("title", "New Title")
    assert model.isDirty, "Item should be dirty after field change"
    assert len(signal_received) > 0, "dirty_state_changed signal should be emitted on first field change"
    assert signal_received[0], "Signal should indicate dirty state is True"
    print("✓ Field change marks item as dirty and emits signal")

    print("\n✅ All dirty tracking tests PASSED!")


def test_save_saves_and_clears_dirty() -> None:
    """
    TEST: test_save_saves_and_clears_dirty

    Verifies: saveItem() method clears dirty state and saves data
    Metric: isDirty becomes False after save, original data updated

    Acceptance: * saveItem emits signal
                * Dirty state cleared after save
                * Changes are persisted
    """

    sys.path.insert(0, str(Path(__file__).parent / ".." / "doorstop_edit"))

    from ui.qml_components import ItemEditorModel

    # Create test item
    test_item = {
        "id": "REQ-002",
        "uid": "REQ-002",
        "title": "Password Reset",
        "description": "Allow users to reset password",
        "status": "draft",
        "priority": "medium",
    }

    # Create and load model
    model = ItemEditorModel()
    model.loadItem(test_item)

    # Verify initial clean state
    assert not model.isDirty, "Item should start clean"

    # Make changes to mark as dirty
    model.setFieldValue("title", "Password Reset Feature")
    model.setFieldValue("status", "active")
    assert model.isDirty, "Item should be dirty after changes"
    print("✓ Changes mark item as dirty")

    # Setup signal tracking
    dirty_signals = []
    model.dirty_state_changed.connect(lambda is_dirty: dirty_signals.append(is_dirty))

    # Save the item
    model.saveItem()

    # Verify dirty state is cleared
    assert not model.isDirty, "Item should not be dirty after save"
    print("✓ Dirty state cleared after save")

    # Verify save signal was emitted
    assert len(dirty_signals) > 0, "dirty_state_changed signal should be emitted on save"
    assert not dirty_signals[-1], "Signal should indicate dirty state is False after save"
    print("✓ Save signal emitted correctly")

    # Verify changes persisted in current data
    saved_data = model.getCurrentItemData()
    assert saved_data["title"] == "Password Reset Feature", (
        f"Expected saved title 'Password Reset Feature', got {saved_data['title']}"
    )
    assert saved_data["status"] == "active", f"Expected saved status 'active', got {saved_data['status']}"
    print("✓ Changes persisted correctly after save")

    print("\n✅ All save tests PASSED!")


def test_red_dot_visible_when_dirty() -> None:
    """
    TEST: test_red_dot_visible_when_dirty

    Verifies: QML dirty indicator (red dot) visibility logic
    Metric: Red dot visible only when isDirty is True

    Acceptance: * Dirty indicator visibility reflects isDirty state
                * Visual feedback changes appropriately
    """

    sys.path.insert(0, str(Path(__file__).parent / ".." / "doorstop_edit"))

    from ui.qml_components import ItemEditorModel

    # Create test item
    test_item = {
        "id": "REQ-003",
        "uid": "REQ-003",
        "title": "User Profile",
        "description": "User profile management",
        "status": "active",
        "priority": "low",
    }

    # Create model
    model = ItemEditorModel()
    model.loadItem(test_item)

    # Test 1: Initially not dirty - red dot should not be visible
    is_dirty = model.isDirty
    assert not is_dirty, "Model should start clean"
    print("✓ Initial state: not dirty (red dot hidden)")

    # Test 2: Make a change - dirty state should be visible
    model.setFieldValue("priority", "high")
    is_dirty = model.isDirty
    assert is_dirty, "Model should be dirty after change"
    print("✓ After change: dirty (red dot visible)")

    # Test 3: Multiple rapid changes - still dirty
    model.setFieldValue("title", "Updated Title")
    model.setFieldValue("description", "Updated description")
    is_dirty = model.isDirty
    assert is_dirty, "Model should remain dirty after multiple changes"
    print("✓ Multiple changes: still dirty (red dot visible)")

    # Test 4: Undo changes - should clear dirty state
    model.undoChanges()
    is_dirty = model.isDirty
    assert not is_dirty, "Model should not be dirty after undo"
    print("✓ After undo: not dirty (red dot hidden)")

    # Test 5: Verify undo signal is emitted
    undo_signals = []
    model.dirty_state_changed.connect(lambda is_dirty: undo_signals.append(is_dirty))

    # Make another change and undo
    model.setFieldValue("title", "Another Title")
    model.undoChanges()

    assert len(undo_signals) > 0, "dirty_state_changed signal should be emitted during undo"
    assert not undo_signals[-1], "Final signal should indicate clean state"
    print("✓ Undo emits correct signals")

    print("\n✅ All red dot visibility tests PASSED!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
