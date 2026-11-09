pragma ComponentBehavior: Bound
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Pane {
    id: panel
    objectName: "pinnedItemsPanel"

    // The host supplies snapshots: {uid, level, header, available}. A row with
    // available: false is still removable, but cannot be opened. Replace the
    // array after a refresh; this component never changes host data itself.
    property var pinnedItems: []
    readonly property alias selectedUid: pins.currentUid
    signal openRequested(string uid)
    signal unpinRequested(string uid)

    implicitWidth: 320
    implicitHeight: 300
    padding: 16
    palette.window: "#14202b"
    palette.text: "#e8f1f2"
    palette.button: "#293d4d"
    palette.buttonText: "#eef4f4"
    palette.highlight: "#7ddac4"
    background: Rectangle { color: "#14202b"; border.color: "#55717a"; border.width: 1 }

    function cleanRows() {
        const source = pinnedItems && typeof pinnedItems.length === "number" ? pinnedItems : []
        const result = []
        for (let i = 0; i < source.length; ++i) {
            const row = source[i]
            if (!row || typeof row.uid !== "string" || !row.uid.trim()) continue
            result.push({uid: row.uid, level: row.level || "", header: row.header || "",
                         available: row.available !== false})
        }
        return result
    }

    function openCurrent() {
        const row = pins.currentRow()
        if (row && row.available) openRequested(row.uid)
    }

    function unpinCurrent() {
        const row = pins.currentRow()
        if (row) unpinRequested(row.uid)
    }

    onPinnedItemsChanged: pins.refresh()
    Component.onCompleted: pins.refresh()

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Label {
            Layout.fillWidth: true
            text: qsTr("PINNED  /  ITEMS")
            font.family: "DejaVu Sans Mono"
            font.pixelSize: 15
            font.bold: true
            color: "#7ddac4"
        }

        Label {
            Layout.fillWidth: true
            visible: pins.rows.length === 0
            text: qsTr("No pinned items yet. Pin an item to keep it here.")
            wrapMode: Text.WordWrap
            color: "#b4cbd0"
            Accessible.name: text
        }

        ListView {
            id: pins
            objectName: "pinnedItemsList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            activeFocusOnTab: true
            keyNavigationWraps: true
            property var rows: []
            property string currentUid: ""
            property bool refreshing: false
            model: rows
            Accessible.role: Accessible.List
            Accessible.name: qsTr("Pinned items. Use arrow keys to select, Enter or Space to open, Delete to unpin.")

            function currentRow() {
                return currentIndex >= 0 && currentIndex < rows.length ? rows[currentIndex] : null
            }

            function refresh() {
                const uid = currentUid
                const oldIndex = currentIndex
                const updated = panel.cleanRows()
                let next = -1
                for (let i = 0; i < updated.length; ++i) {
                    if (updated[i].uid === uid) { next = i; break }
                }
                if (next < 0 && updated.length) next = oldIndex < 0 ? 0 : Math.min(oldIndex, updated.length - 1)
                refreshing = true
                rows = updated
                currentIndex = next
                currentUid = next < 0 ? "" : updated[next].uid
                refreshing = false
            }

            onCurrentIndexChanged: {
                if (!refreshing) {
                    const row = currentRow()
                    currentUid = row ? row.uid : ""
                }
            }
            Keys.onReturnPressed: panel.openCurrent()
            Keys.onEnterPressed: panel.openCurrent()
            Keys.onSpacePressed: panel.openCurrent()
            Keys.onDeletePressed: panel.unpinCurrent()

            delegate: ItemDelegate {
                id: pinRow
                objectName: "pinnedItemRow"
                required property var modelData
                required property int index
                readonly property var entry: modelData
                width: pins.width
                height: 64
                activeFocusOnTab: false
                Accessible.role: Accessible.ListItem
                Accessible.name: entry.uid + (entry.level ? qsTr(", level ") + entry.level : "")
                                 + (entry.header ? qsTr(", ") + entry.header : "")
                                 + (entry.available ? "" : qsTr(", unavailable"))
                Accessible.description: entry.available ? qsTr("Enter or Space opens this item; Delete unpins it.")
                                                        : qsTr("Item unavailable; Delete unpins it.")
                onClicked: {
                    pins.currentIndex = index
                    pins.forceActiveFocus()
                    panel.openCurrent()
                }
                background: Rectangle {
                    color: pins.currentIndex === pinRow.index ? "#236a68" : "#21333e"
                    radius: 4
                    border.width: pins.activeFocus && pins.currentIndex === pinRow.index ? 2 : 0
                    border.color: "#ffffff"
                }
                contentItem: ColumnLayout {
                    spacing: 2
                    Label {
                        Layout.fillWidth: true
                        text: pinRow.entry.uid + (pinRow.entry.level ? qsTr("  ·  ") + pinRow.entry.level : "")
                        font.bold: true
                        color: pinRow.entry.available ? "#e8f1f2" : "#f4d590"
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.fillWidth: true
                        text: pinRow.entry.available ? (pinRow.entry.header || qsTr("Untitled item"))
                                                     : qsTr("Item unavailable")
                        color: "#b4cbd0"
                        elide: Text.ElideRight
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "pinnedOpenButton"
                text: qsTr("Open item")
                enabled: !!pins.currentRow() && pins.currentRow().available
                Accessible.name: qsTr("Open selected pinned item")
                onClicked: panel.openCurrent()
            }
            Button {
                objectName: "pinnedUnpinButton"
                text: qsTr("Unpin")
                enabled: !!pins.currentRow()
                Accessible.name: qsTr("Unpin selected item")
                onClicked: panel.unpinCurrent()
            }
        }
    }
}
