import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Fixed-order workspace panels. The host owns contents and persistence:
// set the four *Content components, restore visibility/sizes, and listen to
// splitterSizesCommitted() when a user finishes dragging a handle.
// This does not implement QDockWidget floating or dock reordering.
Item {
    id: root
    implicitWidth: 1180
    implicitHeight: 620

    // Contents stay loaded when hidden, preserving editor drafts and selection.
    property Component documentContent: null
    property Component itemContent: null
    property Component editorContent: null
    property Component pinnedContent: null

    property bool documentsVisible: true
    property bool itemsVisible: true
    property bool editorVisible: true
    property bool pinnedVisible: false

    // Last panel chosen through the toolbar; empty when all panels are hidden.
    property string currentPanel: "editor" // documents | items | editor | pinned | ""
    readonly property bool horizontal: width >= (pinnedVisible ? 920 : 900)

    // Pixel extents by orientation, to be saved/restored by the host.
    property real documentsWidth: 230
    property real itemsWidth: 300
    property real editorWidth: 520
    property real pinnedWidth: 230
    property real documentsHeight: 150
    property real itemsHeight: 205
    property real editorHeight: 300
    property real pinnedHeight: 150

    signal splitterSizesCommitted()


    // Serializable component-owned state; geometry and persistence stay host-owned.
    function capturePanelState() {
        return { version: 1, documentsVisible: documentsVisible, itemsVisible: itemsVisible,
                 editorVisible: editorVisible, pinnedVisible: pinnedVisible, currentPanel: currentPanel,
                 documentsWidth: documentsWidth, itemsWidth: itemsWidth, editorWidth: editorWidth,
                 pinnedWidth: pinnedWidth, documentsHeight: documentsHeight, itemsHeight: itemsHeight,
                 editorHeight: editorHeight, pinnedHeight: pinnedHeight }
    }

    function restorePanelState(state) {
        var names = ["documents", "items", "editor", "pinned"]
        var minWidths = [180, 210, 300, 190], minHeights = [95, 115, 160, 100]
        if (!state || typeof state !== "object" || state.version !== 1 || typeof state.currentPanel !== "string") return false
        if (state.currentPanel !== "" && names.indexOf(state.currentPanel) < 0) return false
        for (var i = 0; i < names.length; ++i) {
            var name = names[i]
            if (typeof state[name + "Visible"] !== "boolean") return false
            for (var axis of ["Width", "Height"]) {
                var value = state[name + axis]
                if (typeof value !== "number" || !isFinite(value) || value <= 0) return false
            }
        }
        var anyVisible = state.documentsVisible || state.itemsVisible || state.editorVisible || state.pinnedVisible
        if ((anyVisible && !state.currentPanel) || (!anyVisible && state.currentPanel)) return false
        if (state.currentPanel && !state[state.currentPanel + "Visible"]) return false
        for (var j = 0; j < names.length; ++j) root[names[j] + "Visible"] = state[names[j] + "Visible"]
        currentPanel = state.currentPanel
        for (var k = 0; k < names.length; ++k) {
            root[names[k] + "Width"] = Math.max(minWidths[k], state[names[k] + "Width"])
            root[names[k] + "Height"] = Math.max(minHeights[k], state[names[k] + "Height"])
        }
        return true
    }

    function isPanelVisible(name) {
        if (name === "documents") return documentsVisible
        if (name === "items") return itemsVisible
        if (name === "editor") return editorVisible
        if (name === "pinned") return pinnedVisible
        return false
    }

    function selectVisiblePanel() {
        if (editorVisible) currentPanel = "editor"
        else if (itemsVisible) currentPanel = "items"
        else if (documentsVisible) currentPanel = "documents"
        else if (pinnedVisible) currentPanel = "pinned"
        else currentPanel = ""
    }

    function setPanelVisible(name, show) {
        if (name === "documents") documentsVisible = show
        else if (name === "items") itemsVisible = show
        else if (name === "editor") editorVisible = show
        else if (name === "pinned") pinnedVisible = show
        else return
        if (show) currentPanel = name
        else if (currentPanel === name) selectVisiblePanel()
    }

    function togglePanel(name) { setPanelVisible(name, !isPanelVisible(name)) }

    function captureSizes() {
        if (horizontal) {
            if (documentsVisible) documentsWidth = documentsPane.width
            if (itemsVisible) itemsWidth = itemsPane.width
            if (editorVisible) editorWidth = editorPane.width
            if (pinnedVisible) pinnedWidth = pinnedPane.width
        } else {
            if (documentsVisible) documentsHeight = documentsPane.height
            if (itemsVisible) itemsHeight = itemsPane.height
            if (editorVisible) editorHeight = editorPane.height
            if (pinnedVisible) pinnedHeight = pinnedPane.height
        }
        splitterSizesCommitted()
    }

    onDocumentsVisibleChanged: if (!documentsVisible && currentPanel === "documents") selectVisiblePanel()
    onItemsVisibleChanged: if (!itemsVisible && currentPanel === "items") selectVisiblePanel()
    onEditorVisibleChanged: if (!editorVisible && currentPanel === "editor") selectVisiblePanel()
    onPinnedVisibleChanged: if (!pinnedVisible && currentPanel === "pinned") selectVisiblePanel()
    onCurrentPanelChanged: if (currentPanel && !isPanelVisible(currentPanel)) selectVisiblePanel()

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        Flow {
            Layout.fillWidth: true
            spacing: 4
            ToolButton {
                objectName: "documentsToggle"
                text: "Documents"
                highlighted: root.documentsVisible
                font.bold: root.currentPanel === "documents"
                Accessible.name: (root.documentsVisible ? "Hide" : "Show") + " Documents panel"
                onClicked: root.togglePanel("documents")
            }
            ToolButton {
                objectName: "itemsToggle"
                text: "Items"
                highlighted: root.itemsVisible
                font.bold: root.currentPanel === "items"
                Accessible.name: (root.itemsVisible ? "Hide" : "Show") + " Items panel"
                onClicked: root.togglePanel("items")
            }
            ToolButton {
                objectName: "editorToggle"
                text: "Editor"
                highlighted: root.editorVisible
                font.bold: root.currentPanel === "editor"
                Accessible.name: (root.editorVisible ? "Hide" : "Show") + " Editor panel"
                onClicked: root.togglePanel("editor")
            }
            ToolButton {
                objectName: "pinnedToggle"
                text: "Pinned items"
                highlighted: root.pinnedVisible
                font.bold: root.currentPanel === "pinned"
                Accessible.name: (root.pinnedVisible ? "Hide" : "Show") + " Pinned items panel"
                onClicked: root.togglePanel("pinned")
            }
        }

        SplitView {
            id: panels
            objectName: "workspaceSplitView"
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: root.horizontal ? Qt.Horizontal : Qt.Vertical
            onResizingChanged: if (!resizing) root.captureSizes()

            handle: Rectangle {
                implicitWidth: 9
                implicitHeight: 9
                color: SplitHandle.pressed ? "#17a2b8"
                      : SplitHandle.hovered ? "#55717a" : "#344e5c"
                Accessible.name: "Resize workspace panels"
                Accessible.role: Accessible.Splitter
            }

            Frame {
                id: documentsPane
                objectName: "documentsPane"
                visible: root.documentsVisible
                SplitView.fillWidth: !root.itemsVisible && !root.editorVisible && !root.pinnedVisible
                SplitView.fillHeight: !root.itemsVisible && !root.editorVisible && !root.pinnedVisible
                SplitView.preferredWidth: root.documentsWidth
                SplitView.minimumWidth: 180
                SplitView.preferredHeight: root.documentsHeight
                SplitView.minimumHeight: 95
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label { text: "Documents"; font.bold: true }
                    Loader {
                        objectName: "documentContentLoader"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceComponent: root.documentContent
                    }
                }
            }

            Frame {
                id: itemsPane
                objectName: "itemsPane"
                visible: root.itemsVisible
                SplitView.fillWidth: !root.editorVisible && !root.pinnedVisible
                SplitView.fillHeight: !root.editorVisible && !root.pinnedVisible
                SplitView.preferredWidth: root.itemsWidth
                SplitView.minimumWidth: 210
                SplitView.preferredHeight: root.itemsHeight
                SplitView.minimumHeight: 115
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label { text: "Items"; font.bold: true }
                    Loader {
                        objectName: "itemContentLoader"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceComponent: root.itemContent
                    }
                }
            }

            Frame {
                id: editorPane
                objectName: "editorPane"
                visible: root.editorVisible
                SplitView.fillWidth: true
                SplitView.fillHeight: true
                SplitView.preferredWidth: root.editorWidth
                SplitView.minimumWidth: 300
                SplitView.preferredHeight: root.editorHeight
                SplitView.minimumHeight: 160
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label { text: "Editor"; font.bold: true }
                    Loader {
                        objectName: "editorContentLoader"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceComponent: root.editorContent
                    }
                }
            }

            Frame {
                id: pinnedPane
                objectName: "pinnedPane"
                visible: root.pinnedVisible
                SplitView.fillWidth: !root.editorVisible
                SplitView.fillHeight: !root.editorVisible
                SplitView.preferredWidth: root.pinnedWidth
                SplitView.minimumWidth: 190
                SplitView.preferredHeight: root.pinnedHeight
                SplitView.minimumHeight: 100
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label { text: "Pinned items"; font.bold: true }
                    Loader {
                        objectName: "pinnedContentLoader"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceComponent: root.pinnedContent
                    }
                }
            }
        }
    }
}
