import QtQuick 2.15
import QtQuick.Controls 2.15

// The host sets the context before calling popup(), including for Shift+F10/Menu
// on a focused row. Requests are intents; the host owns confirmation and updates.
Menu {
    id: actions

    // "background", "item", or "document". Never infer a target from selection.
    property string contextType: "background"
    property string itemUid: ""
    property string documentPrefix: ""
    property bool invalidItem: false
    property bool projectAvailable: false
    property bool previewAvailable: false
    property bool showInactive: false

    readonly property bool treeContext: contextType === "background" || contextType === "item"
    readonly property bool validItem: contextType === "item" && itemUid.length > 0 && !invalidItem
    readonly property bool validDocument: contextType === "document" && documentPrefix.length > 0

    signal createItemRequested(string afterUid)
    signal deleteItemRequested(string uid)
    signal pinItemRequested(string uid)
    signal popupItemRequested(string uid)
    signal popupDocumentRequested(string prefix)
    signal showInactiveRequested(bool show)
    signal reloadTreeRequested()
    signal expandAllRequested()
    signal collapseAllRequested()

    MenuItem {
        objectName: "createItemAction"
        text: qsTr("New Item")
        visible: actions.treeContext && !actions.invalidItem
        enabled: actions.projectAvailable && visible && (actions.contextType !== "item" || actions.validItem)
        onTriggered: actions.createItemRequested(actions.validItem ? actions.itemUid : "")
    }
    MenuItem {
        objectName: "showInactiveAction"
        text: actions.showInactive ? qsTr("Hide Inactive") : qsTr("Show Inactive")
        visible: actions.treeContext
        enabled: actions.projectAvailable && visible
        onTriggered: actions.showInactiveRequested(!actions.showInactive)
    }
    MenuItem {
        objectName: "reloadTreeAction"
        text: qsTr("Reload Tree")
        visible: actions.treeContext
        enabled: actions.projectAvailable && visible
        onTriggered: actions.reloadTreeRequested()
    }
    MenuItem {
        objectName: "expandAllAction"
        text: qsTr("Expand All")
        visible: actions.treeContext
        enabled: actions.projectAvailable && visible
        onTriggered: actions.expandAllRequested()
    }
    MenuItem {
        objectName: "collapseAllAction"
        text: qsTr("Collapse All")
        visible: actions.treeContext
        enabled: actions.projectAvailable && visible
        onTriggered: actions.collapseAllRequested()
    }
    MenuSeparator { visible: actions.validItem }
    MenuItem {
        objectName: "deleteItemAction"
        text: qsTr("Delete Item")
        visible: actions.validItem
        enabled: actions.projectAvailable && visible
        onTriggered: actions.deleteItemRequested(actions.itemUid)
    }
    MenuItem {
        objectName: "pinItemAction"
        text: qsTr("Pin")
        visible: actions.validItem
        enabled: actions.projectAvailable && visible
        onTriggered: actions.pinItemRequested(actions.itemUid)
    }
    MenuItem {
        objectName: "popupItemAction"
        text: qsTr("Popup")
        visible: actions.validItem
        enabled: actions.previewAvailable && visible
        onTriggered: actions.popupItemRequested(actions.itemUid)
    }
    // The existing QML document-row menu only offers preview, not mutation.
    MenuItem {
        objectName: "popupDocumentAction"
        text: qsTr("Open document in preview window")
        visible: actions.validDocument
        enabled: actions.previewAvailable && visible
        onTriggered: actions.popupDocumentRequested(actions.documentPrefix)
    }
}
