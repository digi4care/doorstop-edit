"""
Test Suite: Pinned Items & State Persistence for QML
Bead: doorstop-edit-qml-frontend-migration-plan-lml.2.3
Slice 5: Pinned Items & State Persistence

TDD Approach: Tests written BEFORE full implementation
Goal: Verify PinnedItemsModel and WindowStateManager work correctly
Acceptance Criteria:
* saveGeometry() returns QByteArray hex
* restoreGeometry loads correctly
* windowWidth/Height properties work
"""

import sys
from pathlib import Path

import pytest


def test_pinned_items_add_remove_works() -> None:
    """
    TEST: test_pinned_items_add_remove_works

    Verifies: PinnedItemsModel add/remove functionality works as expected
    Metric: Items can be added, removed, and cleared correctly

    Acceptance: * Pinned items can be added to list
                * Items can be removed individually
                * All items can be cleared
                * Duplicate items are prevented
    """
    sys.path.insert(0, str(Path(__file__).parent / ".." / "doorstop_edit"))

    from ui.qml_components import PinnedItemsModel

    # Create pinned items model
    model = PinnedItemsModel()

    # Test 1: Initially empty
    assert model.pinnedItemsCount() == 0, "Pinned items should start empty"
    print("✓ Initial state: 0 pinned items")

    # Test 2: Add an item
    item1 = {"id": "REQ-001", "title": "Login Functionality", "status": "active", "priority": "high"}

    model.addPinnedItem(item1)
    assert model.pinnedItemsCount() == 1, f"Expected 1 pinned item, got {model.pinnedItemsCount()}"
    print("✓ Item added successfully")

    # Test 3: Add another item
    item2 = {"id": "REQ-002", "title": "Password Reset", "status": "draft", "priority": "medium"}

    model.addPinnedItem(item2)
    assert model.pinnedItemsCount() == 2, f"Expected 2 pinned items, got {model.pinnedItemsCount()}"
    print("✓ Second item added successfully")

    # Test 4: Prevent duplicates
    model.addPinnedItem(item1)  # Try to add same item again
    assert model.pinnedItemsCount() == 2, "Duplicate items should not be added"
    print("✓ Duplicate item prevented")

    # Test 5: Check isItemPinned
    assert model.isItemPinned("REQ-001"), "REQ-001 should be pinned"
    assert not model.isItemPinned("REQ-999"), "REQ-999 should not be pinned"
    print("✓ isItemPinned works correctly")

    # Test 6: Remove an item
    model.removePinnedItem("REQ-001")
    assert model.pinnedItemsCount() == 1, f"Expected 1 pinned item after removal, got {model.pinnedItemsCount()}"
    assert not model.isItemPinned("REQ-001"), "REQ-001 should no longer be pinned"
    assert model.isItemPinned("REQ-002"), "REQ-002 should still be pinned"
    print("✓ Item removed successfully")

    # Test 7: Clear all items
    model.clearAllPinnedItems()
    assert model.pinnedItemsCount() == 0, "All items should be cleared"
    print("✓ All items cleared successfully")

    print("\n✅ All pinned items add/remove tests PASSED!")


def test_geometry_saved_and_restored_correctly() -> None:
    """
    TEST: test_geometry_saved_and_restored_correctly

    Verifies: WindowStateManager geometry save/restore functionality
    Metric: Geometry data persists correctly between save and restore

    Acceptance: * saveGeometry() returns QByteArray hex
                * restoreGeometry loads correctly
                * windowWidth/Height properties work
    """
    sys.path.insert(0, str(Path(__file__).parent / ".." / "doorstop_edit"))

    from ui.qml_components import WindowStateManager

    # Create window state manager
    manager = WindowStateManager()

    # Test 1: Initial properties
    assert manager.windowWidth == 1200, f"Default width should be 1200, got {manager.windowWidth}"
    assert manager.windowHeight == 800, f"Default height should be 800, got {manager.windowHeight}"
    print("✓ Initial window properties correct")

    # Test 2: Save geometry
    manager.saveGeometry(100, 50, 1400, 900)

    assert manager.windowWidth == 1400, f"Width should be 1400 after save, got {manager.windowWidth}"
    assert manager.windowHeight == 900, f"Height should be 900 after save, got {manager.windowHeight}"
    print("✓ Geometry saved successfully")

    # Test 3: Get saved geometry as QByteArray
    saved_geometry = manager.getSavedGeometry()
    assert not saved_geometry.isEmpty(), "Saved geometry should not be empty"
    assert saved_geometry.size() > 0, "Saved geometry should have data"
    print(f"✓ Saved geometry QByteArray: {saved_geometry.size()} bytes")

    # Test 4: Restore geometry
    manager.restoreGeometry(saved_geometry)

    assert manager.windowWidth == 1400, f"Width should be restored to 1400, got {manager.windowWidth}"
    assert manager.windowHeight == 900, f"Height should be restored to 900, got {manager.windowHeight}"
    print("✓ Geometry restored successfully")

    # Test 5: Verify hex representation works
    geometry_hex = bytes(saved_geometry).hex()
    assert len(geometry_hex) > 0, "Geometry hex representation should not be empty"
    print(f"✓ Geometry hex: {geometry_hex[:32]}...")

    print("\n✅ All geometry save/restore tests PASSED!")


def test_dock_layout_state_preserved() -> None:
    """
    TEST: test_dock_layout_state_preserved

    Verifies: Window state (dock positions, etc.) persists correctly
    Metric: State data can be saved and restored without loss

    Acceptance: * Window state can be saved as string
                * State can be restored correctly
                * Dock layout information is preserved
    """
    sys.path.insert(0, str(Path(__file__).parent / ".." / "doorstop_edit"))

    from ui.qml_components import WindowStateManager

    # Create window state manager
    manager = WindowStateManager()

    # Test 1: Initial state should be empty
    initial_state = manager.getSavedState()
    assert initial_state == "", "Initial state should be empty"
    print("✓ Initial state is empty")

    # Test 2: Save window state (dock layout)
    dock_layout_state = """
    {
        "treeView": {"position": "left", "width": 300, "visible": true},
        "itemEditor": {"position": "bottom", "height": 250, "visible": true},
        "pinnedItems": {"position": "right", "width": 200, "visible": true}
    }
    """

    manager.saveState(dock_layout_state.strip())

    saved_state = manager.getSavedState()
    assert len(saved_state) > 0, "Saved state should not be empty"
    assert "treeView" in saved_state, "Saved state should contain treeView dock info"
    assert "itemEditor" in saved_state, "Saved state should contain itemEditor dock info"
    print("✓ Dock layout state saved successfully")

    # Test 3: Create new manager and restore state
    new_manager = WindowStateManager()
    new_manager.saveState(saved_state)  # Simulate restoring by saving to new manager

    restored_state = new_manager.getSavedState()
    assert restored_state == saved_state, "Restored state should match saved state"
    print("✓ State restored correctly in new manager")

    # Test 4: Verify state contains all dock information
    assert "pinnedItems" in restored_state, "Restored state should contain pinnedItems dock info"
    print("✓ All dock layout information preserved")

    print("\n✅ All dock layout state tests PASSED!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
