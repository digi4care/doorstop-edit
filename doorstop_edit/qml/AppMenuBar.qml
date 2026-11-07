import QtQuick 2.15
import QtQuick.Controls 2.15

// Standalone menu contract. The host owns dialogs, draft confirmation and navigation.
// Confirm unsaved edits before fulfilling openFolderRequested or exitRequested.
MenuBar {
    id: root

    property bool hasProject: false
    property bool hasSelection: false
    property bool documentTreeVisible: true
    property bool itemEditorVisible: true
    property bool pinnedItemsVisible: true

    signal openFolderRequested()
    signal saveItemRequested()
    signal focusProjectLocationRequested()
    signal validateProjectRequested()
    signal settingsRequested()
    signal exitRequested()
    signal documentTreeVisibilityRequested(bool visible)
    signal itemEditorVisibilityRequested(bool visible)
    signal pinnedItemsVisibilityRequested(bool visible)
    signal graphRequested()
    signal validationResultsRequested()
    signal aboutRequested()

    Menu {
        title: qsTr("File")

        MenuItem {
            Accessible.name: qsTr("Open project folder")
            action: Action {
                objectName: "openFolderAction"
                text: qsTr("Open Folder…")
                shortcut: "Ctrl+O"
                onTriggered: root.openFolderRequested()
            }
        }
        MenuItem {
            Accessible.name: qsTr("Save current item")
            action: Action {
                objectName: "saveItemAction"
                text: qsTr("Save Item")
                shortcut: "Ctrl+S"
                enabled: root.hasSelection
                onTriggered: root.saveItemRequested()
            }
        }
        MenuItem {
            Accessible.name: qsTr("Focus project location")
            action: Action {
                objectName: "focusProjectLocationAction"
                text: qsTr("Project Location")
                shortcut: "Ctrl+L"
                onTriggered: root.focusProjectLocationRequested()
            }
        }
        MenuSeparator {}
        MenuItem {
            Accessible.name: qsTr("Validate all documents and items")
            action: Action {
                objectName: "validateProjectAction"
                text: qsTr("Validate Project")
                enabled: root.hasProject
                onTriggered: root.validateProjectRequested()
            }
        }
        MenuItem {
            Accessible.name: qsTr("Open settings")
            action: Action {
                objectName: "settingsAction"
                text: qsTr("Settings…")
                onTriggered: root.settingsRequested()
            }
        }
        MenuSeparator {}
        MenuItem {
            Accessible.name: qsTr("Exit Doorstop Edit")
            action: Action {
                objectName: "exitAction"
                text: qsTr("Exit")
                onTriggered: root.exitRequested()
            }
        }
    }

    Menu {
        title: qsTr("View")

        MenuItem {
            Accessible.name: qsTr("Show document tree")
            action: Action {
                objectName: "documentTreeAction"
                text: qsTr("Document Tree")
                checkable: true
                checked: root.documentTreeVisible
                onTriggered: root.documentTreeVisibilityRequested(!root.documentTreeVisible)
            }
        }
        MenuItem {
            Accessible.name: qsTr("Show item editor")
            action: Action {
                objectName: "itemEditorAction"
                text: qsTr("Item Editor")
                checkable: true
                checked: root.itemEditorVisible
                onTriggered: root.itemEditorVisibilityRequested(!root.itemEditorVisible)
            }
        }
        MenuItem {
            Accessible.name: qsTr("Show pinned items")
            action: Action {
                objectName: "pinnedItemsAction"
                text: qsTr("Pinned Items")
                checkable: true
                checked: root.pinnedItemsVisible
                onTriggered: root.pinnedItemsVisibilityRequested(!root.pinnedItemsVisible)
            }
        }
        MenuSeparator {}
        MenuItem {
            Accessible.name: qsTr("Open project graph")
            action: Action {
                objectName: "graphAction"
                text: qsTr("Project Graph")
                shortcut: "Ctrl+G"
                onTriggered: root.graphRequested()
            }
        }
        MenuItem {
            Accessible.name: qsTr("Open project validation results")
            action: Action {
                objectName: "validationResultsAction"
                text: qsTr("Validation Results")
                enabled: root.hasProject
                onTriggered: root.validationResultsRequested()
            }
        }
    }

    Menu {
        title: qsTr("Help")
        MenuItem {
            Accessible.name: qsTr("About Doorstop Edit")
            action: Action {
                objectName: "aboutAction"
                text: qsTr("About")
                onTriggered: root.aboutRequested()
            }
        }
    }
}
