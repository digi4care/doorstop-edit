import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtWebEngine
import QtWebChannel 1.0

Item {
    id: preview
    property var renderBridge
    readonly property alias webView: web
    implicitHeight: 220
    property string searchStatus: ""
    property int searchMatches: 0
    property int searchActiveMatch: 0
    property bool loadingTrustedPage: false
    function loadTrustedPage() {
        if (!renderBridge) return
        loadingTrustedPage = true
        web.loadHtml(renderBridge.pageHtml, renderBridge.baseUrl)
    }

    // QML's WebEngineView requires a QQmlWebChannel, not a Python QWebChannel.
    // This object forwards the existing HTML_TEMPLATE's `py` WebChannel API.
    QtObject {
        id: py
        WebChannel.id: "py"
        signal html_update_item(string id, string content, bool focus, bool hide)
        signal html_select_item(string id)
        function bridgeReady(generation) { preview.renderBridge.bridgeReady(generation) }
        function open_item(uid) { preview.renderBridge.open_item(uid) }
    }
    WebChannel { id: channel; registeredObjects: [py] }
    Connections {
        target: preview.renderBridge
        function onHtmlUpdateItem(id, content, focus, hide) { py.html_update_item(id, content, focus, hide) }
        function onHtmlSelectItem(id) { py.html_select_item(id) }
        function onPageChanged() { preview.loadTrustedPage() }
    }
    WebEngineView {
        id: web
        objectName: "renderWebView"
        activeFocusOnTab: true
        Accessible.name: qsTr("Document preview")
        anchors.fill: parent
        anchors.topMargin: controls.height + 6
        webChannel: channel
        onLoadingChanged: function(info) {
            if (!preview.renderBridge) return
            if (info.status === WebEngineView.LoadSucceededStatus) {
                preview.loadingTrustedPage = false
                preview.renderBridge.loadSucceeded()
            } else if (info.status === WebEngineView.LoadFailedStatus) {
                preview.loadingTrustedPage = false
                preview.renderBridge.loadFailed(info.errorString)
            }
        }
        onNavigationRequested: function(request) {
            if (!preview.renderBridge) { request.reject(); return }
            if (request.navigationType === WebEngineView.LinkClickedNavigation) {
                request.reject()
                preview.renderBridge.openExternal(request.url.toString())
            } else if (request.navigationType === WebEngineView.ReloadNavigation) {
                request.reject()
                Qt.callLater(function() { preview.renderBridge.reload() })
            } else if (!preview.loadingTrustedPage || !request.url.toString().startsWith("data:")) {
                // Never replace the trusted WebChannel page, including scripted navigations.
                request.reject()
            }
        }
        onFindTextFinished: function(result) {
            preview.searchMatches = result.numberOfMatches
            preview.searchActiveMatch = result.activeMatch
            preview.searchStatus = searchField.text && result.numberOfMatches === 0 ? qsTr("No matches") : ""
        }
        onNewWindowRequested: function(request) {
            // target=_blank must not create an unmanaged browser window either.
            if (preview.renderBridge) preview.renderBridge.openExternal(request.requestedUrl.toString())
        }
    }
    RowLayout {
        id: controls
        anchors.left: parent.left
        anchors.right: parent.right
        height: 40
        spacing: 8
        Label { text: qsTr("Mode"); Accessible.name: qsTr("Preview mode") }
        ComboBox {
            id: modePicker
            objectName: "renderModePicker"
            Layout.preferredWidth: 132
            model: [qsTr("Document"), qsTr("Section"), qsTr("Item")]
            Accessible.name: qsTr("Preview mode")
            onActivated: if (preview.renderBridge) preview.renderBridge.setViewMode(["document", "section", "item"][currentIndex])
            Component.onCompleted: if (preview.renderBridge) currentIndex = ["document", "section", "item"].indexOf(preview.renderBridge.viewMode)
        }
        Button {
            objectName: "renderReloadButton"
            text: qsTr("Reload")
            Accessible.name: qsTr("Reload preview")
            onClicked: if (preview.renderBridge) preview.renderBridge.reload()
        }
        TextField {
            id: searchField
            objectName: "renderSearchField"
            Layout.preferredWidth: Math.min(170, Math.max(85, preview.width * 0.22))
            placeholderText: qsTr("Find in preview")
            Accessible.name: qsTr("Find text in preview")
            onTextChanged: {
                preview.searchStatus = ""
                web.findText(text)
            }
            onAccepted: web.findText(text)
        }
        Label {
            objectName: "renderSearchStatus"
            text: preview.searchStatus
            visible: text.length > 0
            color: "#ffc39f"
            Accessible.name: text
        }
        ProgressBar {
            objectName: "renderProgressBar"
            Layout.fillWidth: true
            from: 0; to: 100
            value: preview.renderBridge ? preview.renderBridge.progress : 0
            visible: !!preview.renderBridge && preview.renderBridge.running
            Accessible.name: qsTr("Preview rendering, %1 percent").arg(Math.round(value))
        }
    }
    Rectangle {
        anchors.fill: web
        visible: !!preview.renderBridge && !!preview.renderBridge.errorMessage
        color: "#db16242b"
        Label {
            objectName: "renderErrorLabel"
            anchors.centerIn: parent
            width: parent.width - 32
            text: preview.renderBridge ? preview.renderBridge.errorMessage : ""
            color: "#ffc39f"
            font.bold: true
            wrapMode: Text.WordWrap
            Accessible.name: text
        }
    }
    onRenderBridgeChanged: loadTrustedPage()
}
