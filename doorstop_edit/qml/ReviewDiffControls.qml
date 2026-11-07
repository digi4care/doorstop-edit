import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Pane {
    id: controls
    // Host state is authoritative: reviewed represents the fingerprint verdict.
    property bool hasItem: false
    property bool reviewed: false
    property bool cleared: true
    property bool canUnreview: false
    property bool canDiff: false
    property bool diffVisible: false
    property string diffMode: "file" // "file" (startup snapshot) or "git"
    property string diffState: "idle" // "idle", "loading", "ready", "error"
    property string diffText: ""
    property string diffError: ""
    property int historyIndex: 0
    property int historyCount: 0
    property string historyLabel: ""
    property string historyAuthor: ""
    property string historyDate: ""

    signal reviewRequested()
    signal unreviewRequested()
    signal clearSuspectsRequested()
    signal diffRequested()
    signal diffModeRequested(string mode)
    signal diffRevisionRequested(int index)

    readonly property bool historyAvailable: hasItem && diffVisible && diffMode === "git"
                                            && diffState === "ready" && historyCount > 0
    objectName: "reviewDiffControls"
    implicitWidth: 420
    implicitHeight: content.implicitHeight + topPadding + bottomPadding
    padding: 14
    palette.window: "#14202b"
    palette.text: "#e8f1f2"
    palette.base: "#243544"
    palette.button: "#293d4d"
    palette.buttonText: "#eef4f4"
    palette.highlight: "#7ddac4"
    background: Rectangle {
        color: "#14202b"
        radius: 8
        border.color: "#55717a"
    }

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Label {
                text: qsTr("REVIEW / CHANGES")
                font.bold: true
                font.letterSpacing: 1.2
                color: "#7ddac4"
            }
            Item { Layout.fillWidth: true }
            Label {
                objectName: "reviewStatus"
                text: !controls.hasItem ? qsTr("No item selected")
                      : controls.reviewed ? qsTr("Reviewed") : qsTr("Not reviewed")
                color: controls.hasItem && !controls.reviewed ? "#ffc39f" : "#e8f1f2"
                Accessible.name: text
            }
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            Button {
                objectName: "reviewAction"
                text: qsTr("Mark reviewed")
                Accessible.name: text
                activeFocusOnTab: true
                enabled: controls.hasItem && !controls.reviewed
                onClicked: controls.reviewRequested()
            }
            Button {
                objectName: "unreviewAction"
                text: qsTr("Remove review")
                Accessible.name: text
                activeFocusOnTab: true
                visible: controls.canUnreview
                enabled: controls.hasItem && controls.reviewed && controls.canUnreview
                onClicked: controls.unreviewRequested()
            }
            Button {
                objectName: "clearSuspectsAction"
                text: qsTr("Clear suspect links")
                Accessible.name: text
                activeFocusOnTab: true
                enabled: controls.hasItem && !controls.cleared
                onClicked: controls.clearSuspectsRequested()
            }
            Button {
                objectName: "diffAction"
                text: qsTr("View changes")
                Accessible.name: text
                activeFocusOnTab: true
                enabled: controls.hasItem && controls.canDiff
                onClicked: controls.diffRequested()
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            visible: controls.hasItem && controls.diffVisible
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Label { text: qsTr("Compare"); color: "#e8f1f2" }
                ComboBox {
                    id: modePicker
                    objectName: "diffModePicker"
                    Layout.preferredWidth: 200
                    model: [qsTr("Since opening"), qsTr("Git history")]
                    Binding { target: modePicker; property: "currentIndex"; value: controls.diffMode === "git" ? 1 : 0 }
                    enabled: controls.canDiff
                    activeFocusOnTab: true
                    Accessible.name: qsTr("Comparison source")
                    onActivated: function(index) { controls.diffModeRequested(index === 1 ? "git" : "file") }
                }
                Item { Layout.fillWidth: true }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: controls.diffMode === "git"
                Button {
                    objectName: "olderDiffAction"
                    text: qsTr("Older")
                    Accessible.name: qsTr("Older change")
                    activeFocusOnTab: true
                    enabled: controls.historyAvailable && controls.historyIndex < controls.historyCount - 1
                    onClicked: controls.diffRevisionRequested(controls.historyIndex + 1)
                }
                Label {
                    objectName: "diffHistoryLabel"
                    Layout.fillWidth: true
                    text: controls.historyLabel
                    color: "#e8f1f2"
                    elide: Text.ElideRight
                    Accessible.name: text
                }
                Button {
                    objectName: "newerDiffAction"
                    text: qsTr("Newer")
                    Accessible.name: qsTr("Newer change")
                    activeFocusOnTab: true
                    enabled: controls.historyAvailable && controls.historyIndex > 0
                    onClicked: controls.diffRevisionRequested(controls.historyIndex - 1)
                }
            }
            Label {
                Layout.fillWidth: true
                visible: controls.diffMode === "git" && (controls.historyAuthor || controls.historyDate)
                text: controls.historyAuthor + (controls.historyAuthor && controls.historyDate ? " · " : "")
                      + controls.historyDate
                color: "#afc4ca"
                elide: Text.ElideRight
                Accessible.name: text
            }
            Label {
                objectName: "diffMessage"
                Layout.fillWidth: true
                visible: controls.diffState !== "ready" || !controls.diffText
                text: controls.diffState === "loading" ? qsTr("Loading changes…")
                      : controls.diffState === "error" ? (controls.diffError || qsTr("Changes unavailable"))
                      : controls.diffState === "ready" ? qsTr("No changes") : qsTr("Select a comparison")
                color: controls.diffState === "error" ? "#ffc39f" : "#afc4ca"
                wrapMode: Text.WordWrap
                Accessible.name: text
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 240
                visible: controls.diffState === "ready" && !!controls.diffText
                clip: true
                TextArea {
                    objectName: "diffContent"
                    text: controls.diffText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.NoWrap
                    textFormat: TextEdit.PlainText
                    font.family: "monospace"
                    color: "#e8f1f2"
                    activeFocusOnTab: true
                    Accessible.name: qsTr("Changes")
                }
            }
        }
    }
}
