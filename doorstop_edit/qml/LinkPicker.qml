import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Standalone view: the host supplies project-wide candidates and current links,
// applies requested edits, and publishes a fresh snapshot.
Pane {
    id: picker
    objectName: "linkPicker"
    // candidateItems: [{uid, header, level, valid?}]; valid === false blocks new links.
    property var candidateItems: []
    // linkedTargets: [{uid, status}]; status: ok, suspect, unknown or unresolved.
    property var linkedTargets: []
    property string sourceUid: ""
    property bool inspectEnabled: false
    property var results: []
    signal addRequested(string uid)
    signal removeRequested(string uid)
    signal inspectRequested(string uid)

    readonly property var selectedRow: results[resultList.currentIndex] || null
    readonly property color ink: "#e8f1f2"
    readonly property color muted: "#a5bcc4"
    readonly property color accent: "#7ddac4"

    implicitWidth: 440
    implicitHeight: 460
    padding: 16
    palette.window: "#14202b"
    palette.text: ink
    palette.base: "#243544"
    palette.button: "#293d4d"
    palette.buttonText: ink
    palette.highlight: accent
    background: Rectangle { color: "#14202b"; border.color: "#55717a" }

    function focusSearch() { searchField.forceActiveFocus() }

    function updateResults() {
        const linked = Object.create(null)
        const candidates = Object.create(null)
        const rows = []
        const terms = searchField.text.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
        const links = linkedTargets || []
        const items = candidateItems || []
        for (let i = 0; i < links.length; ++i) {
            const entry = links[i]
            if (entry && typeof entry.uid === "string" && entry.uid)
                linked[entry.uid] = entry.status || "unknown"
        }
        for (let i = 0; i < items.length; ++i) {
            const item = items[i]
            if (!item || typeof item.uid !== "string" || !item.uid || item.uid === sourceUid
                    || candidates[item.uid]) continue
            candidates[item.uid] = true
            rows.push({uid: item.uid, header: String(item.header || ""), level: String(item.level || ""),
                       linked: Object.prototype.hasOwnProperty.call(linked, item.uid),
                       status: linked[item.uid] || "", available: item.valid !== false, missing: false})
        }
        // Broken or self-referencing existing links must remain removable.
        for (let i = 0; i < links.length; ++i) {
            const entry = links[i]
            if (!entry || typeof entry.uid !== "string" || !entry.uid || candidates[entry.uid]) continue
            candidates[entry.uid] = true
            rows.push({uid: entry.uid, header: "", level: "", linked: true,
                       status: entry.status || "unresolved", available: false, missing: true})
        }
        rows.sort(function(a, b) { return a.uid.localeCompare(b.uid) })
        results = rows.filter(function(row) {
            const text = (row.uid + " " + row.header + " " + row.level).toLocaleLowerCase()
            return terms.every(function(term) { return text.indexOf(term) !== -1 })
        })
        resultList.currentIndex = results.length ? 0 : -1
    }

    function moveSelection(delta) {
        if (!results.length) return
        resultList.currentIndex = Math.max(0, Math.min(results.length - 1, resultList.currentIndex + delta))
        resultList.positionViewAtIndex(resultList.currentIndex, ListView.Contain)
    }

    function activateSelection() {
        const row = selectedRow
        if (!row) return
        if (row.linked) removeRequested(row.uid)
        else if (row.available) addRequested(row.uid)
    }

    onCandidateItemsChanged: updateResults()
    onLinkedTargetsChanged: updateResults()
    onSourceUidChanged: updateResults()
    Component.onCompleted: updateResults()

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Label {
            text: qsTr("Links")
            font.pixelSize: 20
            font.weight: Font.DemiBold
            color: picker.ink
        }
        TextField {
            id: searchField
            objectName: "linkSearch"
            Layout.fillWidth: true
            placeholderText: qsTr("Search by ID or title")
            Accessible.name: qsTr("Search link targets")
            onTextChanged: picker.updateResults()
            Keys.onDownPressed: picker.moveSelection(1)
            Keys.onUpPressed: picker.moveSelection(-1)
            Keys.onReturnPressed: picker.activateSelection()
            Keys.onEnterPressed: picker.activateSelection()
        }
        Label {
            Layout.fillWidth: true
            color: picker.muted
            text: qsTr("%1 targets · %2 linked").arg(picker.results.length).arg(
                      picker.results.filter(function(row) { return row.linked }).length)
        }
        ListView {
            id: resultList
            objectName: "linkResults"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: picker.results
            currentIndex: -1
            spacing: 4
            Accessible.name: qsTr("Link targets")
            Keys.onReturnPressed: picker.activateSelection()
            Keys.onEnterPressed: picker.activateSelection()
            delegate: ItemDelegate {
                id: rowDelegate
                required property var modelData
                required property int index
                width: resultList.width
                height: 60
                highlighted: resultList.currentIndex === index
                Accessible.name: modelData.uid + ", " + (modelData.header || qsTr("Target unavailable"))
                                 + ", " + picker.statusText(modelData)
                onClicked: { resultList.currentIndex = index; resultList.forceActiveFocus() }
                background: Rectangle {
                    radius: 4
                    color: rowDelegate.highlighted ? "#295260" : "#20323f"
                    border.color: rowDelegate.highlighted ? picker.accent : "#354d58"
                }
                contentItem: Column {
                    spacing: 4
                    Label {
                        width: parent.width
                        elide: Text.ElideRight
                        text: rowDelegate.modelData.uid + (rowDelegate.modelData.header
                              ? "  —  " + rowDelegate.modelData.header : "")
                        color: picker.ink
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: picker.statusText(rowDelegate.modelData)
                        color: rowDelegate.modelData.status === "suspect"
                               || !rowDelegate.modelData.available ? "#eec889" : picker.muted
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            visible: !picker.results.length
            text: searchField.text ? qsTr("No matching targets") : qsTr("No targets available")
            color: picker.muted
        }
        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "linkChange"
                text: picker.selectedRow && picker.selectedRow.linked ? qsTr("Remove link") : qsTr("Add link")
                enabled: !!picker.selectedRow && (picker.selectedRow.linked || picker.selectedRow.available)
                Accessible.name: enabled ? text + ": " + picker.selectedRow.uid : text
                onClicked: picker.activateSelection()
            }
            Button {
                objectName: "linkInspect"
                text: qsTr("Inspect")
                visible: picker.inspectEnabled
                enabled: picker.inspectEnabled && !!picker.selectedRow && picker.selectedRow.available
                Accessible.name: enabled ? qsTr("Inspect %1").arg(picker.selectedRow.uid) : qsTr("Inspect target")
                onClicked: picker.inspectRequested(picker.selectedRow.uid)
            }
            Item { Layout.fillWidth: true }
        }
    }

    function statusText(row) {
        if (row.missing) return qsTr("Linked · missing target")
        if (!row.available) return row.linked ? qsTr("Linked · invalid target") : qsTr("Invalid target")
        if (!row.linked) return qsTr("Not linked")
        if (row.status === "suspect") return qsTr("Linked · needs review")
        if (row.status === "unresolved") return qsTr("Linked · missing target")
        if (row.status === "unknown") return qsTr("Linked · status unknown")
        return qsTr("Linked")
    }
}
