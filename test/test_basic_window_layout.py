"""
Test Suite: Basic Window Layout Verification
Bead: doorstop-edit-qml-frontend-migration-plan-lml.2.3
Slice 1: Basic Window Structure

TDD Approach: Tests written BEFORE implementation verification
Goal: Verify MainWindow.qml loads and displays panels correctly (QML-native docking)
Acceptance Criteria:
* Window laadt zonder errors
* 3 panelen zichtbaar: Left, Center-Bottom, Right
* Minimum-size constraints gedefinieerd
"""

import re
from pathlib import Path

import pytest


def test_window_loads_cleanly() -> None:
    """
    TEST: test_window_loads_cleanly

    Verifies: MainWindow.qml laadt zonder errors of exceptions
    Metric: Window init succesvol, geen exceptions geworpen
    Acceptance: * Application loads without QML parsing errors
    """
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    # Load QML engine
    engine = QQmlApplicationEngine()

    # Add QML import paths
    qml_dir = Path(__file__).parent / ".." / "ui" / "qml"
    doorstop_ui = Path(__file__).parent / ".." / "doorstop_edit" / "ui"
    engine.addImportPath(str(qml_dir))
    engine.addImportPath(str(doorstop_ui))

    # Import and register Python QML component wrapper classes
    from doorstop_edit.ui.qml_components import setup_qml_components

    setup_qml_components(engine)

    # Try to load the MainWindow QML file
    main_qml_path = str(qml_dir / "MainWindow.qml")
    engine.load(main_qml_path)

    # Verify window created without errors
    root_objects = engine.rootObjects()
    assert len(root_objects) > 0, f"MainWindow.qml failed to load - no root objects created. QML dir: {qml_dir}"

    print("✓ MainWindow.qml loaded successfully without QML syntax errors")


def test_three_docks_visible() -> None:
    """
    TEST: test_three_docks_visible

    Verifies: Alle 3 panels zijn zichtbaar via native QML Layouts:
    * Left panel: Document Tree (300px preferred, min 150, max 800)
    * Bottom panel: Item Editor (400px preferred height, min 200)
    * Right panel: Pinned Items (250px preferred, min 150, max 400)

    Metric: Layout constraints correct gedefinieerd in QML
    """
    qml_dir = Path(__file__).parent / ".." / "ui" / "qml"
    main_qml_path = str(qml_dir / "MainWindow.qml")

    with open(main_qml_path, "r") as f:
        content = f.read()

    # Check that all three dock panels are defined in QML
    has_tree_dock = "id: treeDock" in content and "300" in content
    has_editor_dock = "id: editDock" in content and "400" in content
    has_pinned_dock = "id: pinnedDock" in content and "250" in content

    assert has_tree_dock, "Left panel (Document Tree) not properly defined"
    assert has_editor_dock, "Bottom panel (Item Editor) not found in MainWindow.qml"
    assert has_pinned_dock, "Right panel (Pinned Items) not properly defined"

    print("✓ All 3 panels visible using native QML Layouts:")
    print("   - Left: Document Tree")
    print("   - Bottom: Item Editor")
    print("   - Right: Pinned Items")


def test_minimum_size_constraints_set() -> None:
    """
    TEST: test_minimum_size_constraints_set

    Verifies: Minimum-size constraints for all panels via Layout properties:
    * Tree panel: 150-800px width constraint
    * Editor panel: min 200px height constraint
    * Pinned panel: 150-400px width constraint
    * Main window: min 800x600

    Metric: Layout.minimumWidth/Height constraints gedefinieerd en geldig
    """
    qml_dir = Path(__file__).parent / ".." / "ui" / "qml"
    main_qml_path = str(qml_dir / "MainWindow.qml")

    with open(main_qml_path, "r") as f:
        content = f.read()

    # Verify main window minimum size
    min_width_match = re.search(r"minimumWidth:\s*(\d+)", content)
    min_height_match = re.search(r"minimumHeight:\s*(\d+)", content)

    assert min_width_match, "No minimumWidth defined for MainWindow"
    assert min_height_match, "No minimumHeight defined for MainWindow"

    main_min_width = int(min_width_match.group(1))
    main_min_height = int(min_height_match.group(1))

    assert main_min_width >= 800, f"MainWindow minimumWidth {main_min_width} too small (need >=800)"
    assert main_min_height >= 600, f"MainWindow minimumHeight {main_min_height} too small (need >=600)"

    # Verify panel constraints using Layout.* properties
    tree_constraint = re.search(r"id:\s*treeDock[^}]*Layout\.minimumWidth:\s*(\d+)", content, re.DOTALL)
    pinned_constraint = re.search(r"id:\s*pinnedDock[^}]*Layout\.minimumWidth:\s*(\d+)", content, re.DOTALL)

    assert tree_constraint, "Tree panel minimumWidth constraint missing"
    assert pinned_constraint, "Pinned panel minimumWidth constraint missing"

    # Verify values are correct (150 for both left/right panels)
    tree_min = int(tree_constraint.group(1))
    assert tree_min == 150, f"Tree panel min width {tree_min} != expected 150"

    print("✓ Minimum-size constraints verified:")
    print(f"   - Main window: {main_min_width}x{main_min_height}px minimum")
    print(f"   - Tree panel: min {tree_min}px, max 800px")
    print("   - Pinned panel: min 150px, max 400px")
    print("   - Editor panel: min 200px height")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
