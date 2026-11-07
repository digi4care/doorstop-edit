import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Presentation and intent only: the host owns the document tree, confirmation,
// atomic mutations, refresh, and error reporting (including stale-tree errors).
Pane {
    id: actions
    objectName: "documentManagementActions"

    property bool projectAvailable: false
    property string selectedPrefix: ""
    property string parentPrefix: ""
    property var childPrefixes: []
    property bool reorderAvailable: false

    readonly property bool hasSelection: projectAvailable && selectedPrefix.length > 0
    readonly property bool hasChildren: childPrefixes && childPrefixes.length > 0

    signal addDocumentRequested(string parentPrefix)
    signal removeDocumentRequested(string prefix)
    signal reviewAllRequested(string prefix)
    signal clearLinksRequested(string prefix)
    signal reorderLevelsRequested(string prefix)

    padding: 12
    background: Rectangle {
        radius: 6
        color: actions.palette.base
        border.color: actions.palette.mid
    }

    ColumnLayout {
        width: actions.availableWidth
        spacing: 9

        Label {
            Layout.fillWidth: true
            text: qsTr("DOCUMENT / ACTIONS")
            font.bold: true
            font.letterSpacing: 1
            color: actions.palette.highlight
            Accessible.name: text
        }
        Label {
            Layout.fillWidth: true
            text: !actions.projectAvailable ? qsTr("Open a project to manage documents.")
                  : !actions.hasSelection ? qsTr("Select a document, or add a top-level document.")
                  : actions.parentPrefix ? qsTr("%1 · child of %2").arg(actions.selectedPrefix).arg(actions.parentPrefix)
                  : qsTr("%1 · top-level document").arg(actions.selectedPrefix)
            elide: Text.ElideRight
            Accessible.name: text
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8

            Button {
                objectName: "addDocumentAction"
                text: qsTr("Add document…")
                enabled: actions.projectAvailable
                activeFocusOnTab: true
                Accessible.name: text
                Accessible.description: qsTr("The project will ask for a prefix and parent document.")
                onClicked: if (enabled) actions.addDocumentRequested(actions.hasSelection ? actions.selectedPrefix : "")
            }
            Button {
                objectName: "removeDocumentAction"
                text: qsTr("Remove document…")
                enabled: actions.hasSelection && !actions.hasChildren
                activeFocusOnTab: true
                Accessible.name: text
                Accessible.description: actions.hasChildren
                    ? qsTr("Remove child documents first: %1").arg(actions.childPrefixes.join(", "))
                    : qsTr("The project will ask for confirmation before deleting the selected document.")
                onClicked: if (enabled) actions.removeDocumentRequested(actions.selectedPrefix)
            }
        }
        Label {
            Layout.fillWidth: true
            objectName: "childDocumentsWarning"
            visible: actions.hasSelection && actions.hasChildren
            text: qsTr("Remove child documents first: %1").arg(actions.childPrefixes.join(", "))
            wrapMode: Text.WordWrap
            Accessible.name: text
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: actions.palette.mid
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("SELECTED DOCUMENT")
            font.bold: true
            font.letterSpacing: 1
            color: actions.palette.highlight
            Accessible.name: text
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8

            Button {
                objectName: "reviewAllAction"
                text: qsTr("Review all…")
                enabled: actions.hasSelection
                activeFocusOnTab: true
                Accessible.name: qsTr("Mark all items in the selected document as reviewed")
                onClicked: if (enabled) actions.reviewAllRequested(actions.selectedPrefix)
            }
            Button {
                objectName: "clearLinksAction"
                text: qsTr("Clear suspect links…")
                enabled: actions.hasSelection
                activeFocusOnTab: true
                Accessible.name: qsTr("Clear all suspect links in the selected document")
                onClicked: if (enabled) actions.clearLinksRequested(actions.selectedPrefix)
            }
            Button {
                objectName: "reorderLevelsAction"
                text: qsTr("Reorder levels…")
                enabled: actions.hasSelection && actions.reorderAvailable
                activeFocusOnTab: true
                Accessible.name: qsTr("Automatically reorder item levels in the selected document")
                onClicked: if (enabled) actions.reorderLevelsRequested(actions.selectedPrefix)
            }
        }
    }
}
