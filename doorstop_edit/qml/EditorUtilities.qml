import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// The host owns the item, focused text field, saved wrap preference and all side effects.
// In particular, undoRequested means "ask before restoring the entire item", not Ctrl+Z.
ToolBar {
    id: utilities
    objectName: "editorUtilities"

    property string itemUid: ""
    property bool undoAvailable: false
    property bool formatAvailable: false
    property bool wrapText: false

    signal undoRequested()
    signal formatRequested()
    signal wrapTextRequested(bool wrapped)
    signal copyUidRequested(string uid)

    implicitHeight: actions.implicitHeight + topPadding + bottomPadding

    RowLayout {
        id: actions
        anchors.fill: parent
        spacing: 6

        ToolButton {
            id: undoButton
            objectName: "undoItemButton"
            text: "Undo item"
            enabled: utilities.itemUid.length > 0 && utilities.undoAvailable
            activeFocusOnTab: true
            Accessible.name: "Undo all changes to selected item"
            ToolTip.visible: hovered
            ToolTip.text: "Restore the selected item after confirmation"
            onClicked: utilities.undoRequested()
        }

        ToolButton {
            id: formatButton
            objectName: "formatTextButton"
            text: "Format text"
            enabled: utilities.itemUid.length > 0 && utilities.formatAvailable
            activeFocusOnTab: true
            Accessible.name: "Format focused text field"
            ToolTip.visible: hovered
            ToolTip.text: "Format focused text field (Alt+Q)"
            onClicked: utilities.formatRequested()
        }

        ToolButton {
            id: wrapButton
            objectName: "wrapTextButton"
            text: utilities.wrapText ? "Wrap: On" : "Wrap: Off"
            activeFocusOnTab: true
            Accessible.name: utilities.wrapText ? "Text wrap on" : "Text wrap off"
            ToolTip.visible: hovered
            ToolTip.text: "Toggle text wrapping in the editor"
            onClicked: utilities.wrapTextRequested(!utilities.wrapText)
        }

        Item { Layout.fillWidth: true }

        ToolButton {
            id: copyButton
            objectName: "copyUidButton"
            text: "Copy UID"
            enabled: utilities.itemUid.length > 0
            activeFocusOnTab: true
            Accessible.name: "Copy selected item UID"
            ToolTip.visible: hovered
            ToolTip.text: "Copy the selected item UID"
            onClicked: utilities.copyUidRequested(utilities.itemUid)
        }
    }

    // Item-level undo deliberately has no Ctrl+Z shortcut: that belongs to text editing.
    Shortcut {
        sequence: "Alt+Q"
        context: Qt.WindowShortcut
        enabled: utilities.itemUid.length > 0 && utilities.formatAvailable
        onActivated: utilities.formatRequested()
    }
}
