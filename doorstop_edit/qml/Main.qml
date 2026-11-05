import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: root
    width: 1180
    height: 720
    minimumWidth: 440
    minimumHeight: 560
    visible: true
    title: backend.projectRoot ? "Doorstop Edit — " + backend.projectRoot : "Doorstop Edit"

    property string selectedDocumentPrefix: ""
    property string savedHeader: ""
    property string savedText: ""
    property string editorUid: ""
    property bool externalConflict: false
    property bool saveInProgress: false
    readonly property var selection: backend.selectedItem || ({})
    readonly property bool hasSelection: !!selection.uid
    readonly property bool isDirty: hasSelection
                                    && (headerField.text !== savedHeader || bodyField.text !== savedText)

    function loadSelection() {
        editorUid = selection.uid || ""
        externalConflict = false
        headerField.text = selection.header === undefined || selection.header === null
                           ? "" : String(selection.header)
        bodyField.text = selection.text === undefined || selection.text === null
                         ? "" : String(selection.text)
        savedHeader = headerField.text
        savedText = bodyField.text
    }

    function selectionUpdated() {
        const nextUid = selection.uid || ""
        if (nextUid !== editorUid) {
            loadSelection()
            return
        }
        const nextHeader = selection.header === undefined || selection.header === null
                           ? "" : String(selection.header)
        const nextText = selection.text === undefined || selection.text === null
                         ? "" : String(selection.text)
        if (saveInProgress && nextHeader === headerField.text && nextText === bodyField.text) {
            savedHeader = nextHeader
            savedText = nextText
            externalConflict = false
        } else if (isDirty) {
            if (nextHeader !== savedHeader || nextText !== savedText) {
                savedHeader = nextHeader
                savedText = nextText
                externalConflict = true
            }
        } else if (nextHeader !== savedHeader || nextText !== savedText) {
            loadSelection()
        }
    }

    function confirmLeaving(action) {
        if (isDirty) {
            discardDialog.pendingAction = action
            discardDialog.open()
        } else {
            action()
        }
    }

    function saveCurrent() {
        if (!hasSelection)
            return
        saveInProgress = true
        backend.saveSelected(headerField.text, bodyField.text)
        saveInProgress = false
        // The backend emits selectedItemChanged before saveSelected returns.
        // Only acknowledge a save if its selected item matches the draft.
        const saved = backend.selectedItem
        if (!backend.errorMessage && saved.uid === editorUid
                && saved.header === headerField.text && saved.text === bodyField.text) {
            savedHeader = headerField.text
            savedText = bodyField.text
            externalConflict = false
        }
    }

    Component.onCompleted: {
        projectPath.text = backend.projectRoot || ""
        loadSelection()
    }

    Connections {
        target: backend
        function onSelectedItemChanged() { root.selectionUpdated() }
        function onProjectRootChanged() {
            projectPath.text = backend.projectRoot || ""
            root.selectedDocumentPrefix = ""
            documentList.currentIndex = -1
            itemList.currentIndex = -1
        }
    }

    Shortcut {
        sequence: "Ctrl+O"
        onActivated: root.confirmLeaving(function() { backend.openProjectPicker() })
    }
    Shortcut {
        sequence: "Ctrl+L"
        onActivated: { projectPath.forceActiveFocus(); projectPath.selectAll() }
    }
    Shortcut {
        sequence: "Ctrl+S"
        enabled: root.hasSelection
        onActivated: root.saveCurrent()
    }

    Dialog {
        id: discardDialog
        property var pendingAction: null
        title: "Discard unsaved changes?"
        modal: true
        width: 340
        anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.Yes | Dialog.No
        Label {
            text: "Your edits to this item will be lost. Continue?"
            wrapMode: Text.WordWrap
            width: parent.width
        }
        onAccepted: {
            const action = pendingAction
            pendingAction = null
            if (action)
                action()
        }
        onRejected: pendingAction = null
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        GridLayout {
            objectName: "projectControls"
            Layout.fillWidth: true
            columns: root.width < 720 ? 2 : 4
            columnSpacing: 8
            rowSpacing: 8

            Label { text: "Project"; font.bold: true }
            TextField {
                id: projectPath
                objectName: "projectPath"
                Layout.fillWidth: true
                placeholderText: "Project folder path"
                Accessible.name: "Project folder path"
                activeFocusOnTab: true
                onAccepted: {
                    const path = text.trim()
                    if (path)
                        root.confirmLeaving(function() { backend.openProject(path) })
                }
            }
            Button {
                objectName: "openPathButton"
                text: "Open path"
                enabled: projectPath.text.trim().length > 0
                Accessible.name: "Open project at entered path"
                onClicked: {
                    const path = projectPath.text.trim()
                    root.confirmLeaving(function() { backend.openProject(path) })
                }
            }
            Button {
                objectName: "browseButton"
                text: "Browse…"
                Accessible.name: "Choose project folder"
                onClicked: root.confirmLeaving(function() { backend.openProjectPicker() })
            }
        }

        SplitView {
            id: workspace
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: root.width >= 900 ? Qt.Horizontal : Qt.Vertical

            Frame {
                SplitView.preferredWidth: 230
                SplitView.minimumWidth: 180
                SplitView.preferredHeight: 150
                SplitView.minimumHeight: 95

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label { text: "Documents"; font.bold: true }
                    ListView {
                        id: documentList
                        objectName: "documentList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        activeFocusOnTab: true
                        keyNavigationWraps: true
                        model: backend.documents
                        Accessible.name: "Document list"
                        Accessible.role: Accessible.List
                        Keys.onReturnPressed: if (currentItem) currentItem.activate()
                        Keys.onEnterPressed: if (currentItem) currentItem.activate()
                        Keys.onSpacePressed: if (currentItem) currentItem.activate()

                        delegate: ItemDelegate {
                            id: documentDelegate
                            objectName: "documentRow"
                            readonly property var entry: typeof modelData === "object" && modelData !== null
                                                         ? modelData : model
                            readonly property string prefix: entry.prefix === undefined ? "" : String(entry.prefix)
                            width: documentList.width
                            height: 56
                            highlighted: prefix === root.selectedDocumentPrefix && prefix.length > 0
                            Accessible.name: prefix + ", " + (entry.count || 0) + " items"
                            Accessible.role: Accessible.ListItem

                            function activate() {
                                if (!prefix || prefix === root.selectedDocumentPrefix)
                                    return
                                root.confirmLeaving(function() {
                                    documentList.currentIndex = index
                                    itemList.currentIndex = -1
                                    root.selectedDocumentPrefix = prefix
                                    backend.selectDocument(prefix)
                                })
                            }
                            onClicked: activate()
                            Rectangle {
                                objectName: "documentFocusOutline"
                                anchors.fill: parent
                                anchors.margins: 2
                                z: 1
                                color: "transparent"
                                radius: 4
                                border.width: documentList.activeFocus && documentList.currentIndex === index ? 2 : 0
                                border.color: documentDelegate.highlighted
                                              ? root.palette.highlightedText : root.palette.highlight
                            }
                            contentItem: ColumnLayout {
                                spacing: 1
                                Label {
                                    Layout.fillWidth: true
                                    text: documentDelegate.prefix + "  ·  " + (documentDelegate.entry.count || 0)
                                    font.bold: documentDelegate.highlighted
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: documentDelegate.entry.parent || documentDelegate.entry.path || ""
                                    opacity: 0.7
                                    font.pixelSize: 11
                                    elide: Text.ElideMiddle
                                }
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: documentList.count === 0
                        text: backend.projectRoot ? "No documents in this project." : "Open a project to see documents."
                        wrapMode: Text.WordWrap
                        opacity: 0.7
                    }
                }
            }

            Frame {
                SplitView.preferredWidth: 300
                SplitView.minimumWidth: 210
                SplitView.preferredHeight: 205
                SplitView.minimumHeight: 115

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label {
                        text: root.selectedDocumentPrefix ? "Items · " + root.selectedDocumentPrefix : "Items"
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                    ListView {
                        id: itemList
                        objectName: "itemList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        activeFocusOnTab: true
                        keyNavigationWraps: true
                        model: backend.items
                        Accessible.name: "Item list"
                        Accessible.role: Accessible.List
                        Keys.onReturnPressed: if (currentItem) currentItem.activate()
                        Keys.onEnterPressed: if (currentItem) currentItem.activate()
                        Keys.onSpacePressed: if (currentItem) currentItem.activate()

                        delegate: ItemDelegate {
                            id: itemDelegate
                            objectName: "itemRow"
                            readonly property var entry: typeof modelData === "object" && modelData !== null
                                                         ? modelData : model
                            readonly property string uid: entry.uid === undefined ? "" : String(entry.uid)
                            width: itemList.width
                            height: 56
                            highlighted: uid.length > 0 && uid === root.selection.uid
                            Accessible.name: uid + ", " + (entry.header || "No header")
                            Accessible.role: Accessible.ListItem

                            function activate() {
                                if (!uid || uid === root.selection.uid)
                                    return
                                root.confirmLeaving(function() {
                                    itemList.currentIndex = index
                                    backend.selectItem(uid)
                                })
                            }
                            onClicked: activate()
                            Rectangle {
                                objectName: "itemFocusOutline"
                                anchors.fill: parent
                                anchors.margins: 2
                                z: 1
                                color: "transparent"
                                radius: 4
                                border.width: itemList.activeFocus && itemList.currentIndex === index ? 2 : 0
                                border.color: itemDelegate.highlighted
                                              ? root.palette.highlightedText : root.palette.highlight
                            }
                            contentItem: ColumnLayout {
                                spacing: 1
                                Label {
                                    Layout.fillWidth: true
                                    text: itemDelegate.uid + (itemDelegate.entry.level !== undefined
                                                              ? "  ·  Level " + itemDelegate.entry.level : "")
                                          + (itemDelegate.entry.active === false ? "  ·  Inactive" : "")
                                          + (itemDelegate.entry.normative === false ? "  ·  Informative" : "")
                                    font.bold: itemDelegate.highlighted
                                    elide: Text.ElideRight
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: itemDelegate.entry.header || "No header"
                                    opacity: 0.7
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        visible: itemList.count === 0
                        text: root.selectedDocumentPrefix ? "No items in this document." : "Select a document to see items."
                        wrapMode: Text.WordWrap
                        opacity: 0.7
                    }
                }
            }

            Frame {
                SplitView.fillWidth: true
                SplitView.fillHeight: true
                SplitView.minimumWidth: 300
                SplitView.minimumHeight: 220

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: root.hasSelection
                                  ? root.selection.uid + (root.selection.level !== undefined
                                                            ? "  ·  Level " + root.selection.level : "")
                                  : "Select an item to edit"
                            font.bold: true
                            elide: Text.ElideRight
                            Accessible.name: "Selected item"
                        }
                        Label {
                            visible: root.isDirty
                            text: "Unsaved changes"
                            Accessible.name: "Unsaved changes"
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        objectName: "conflictMessage"
                        visible: root.externalConflict
                        text: "This item changed outside the editor. Your draft is preserved; saving will replace the newer version."
                        wrapMode: Text.WordWrap
                        color: root.palette.text
                        font.bold: true
                        Accessible.name: "Conflict: " + text
                    }
                    Label { text: "Header"; visible: root.hasSelection }
                    TextField {
                        id: headerField
                        objectName: "headerField"
                        Layout.fillWidth: true
                        enabled: root.hasSelection
                        placeholderText: "Item header"
                        Accessible.name: "Item header"
                        activeFocusOnTab: true
                    }
                    Label { text: "Text"; visible: root.hasSelection }
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        TextArea {
                            id: bodyField
                            objectName: "bodyField"
                            enabled: root.hasSelection
                            wrapMode: TextArea.Wrap
                            placeholderText: root.hasSelection ? "Item text" : "Select an item to edit its text."
                            Accessible.name: "Item text"
                            activeFocusOnTab: true
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "Save"
                            enabled: root.hasSelection
                            Accessible.name: "Save selected item"
                            onClicked: root.saveCurrent()
                        }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Label {
                Layout.fillWidth: true
                text: backend.errorMessage ? "Error: " + backend.errorMessage : ""
                visible: text.length > 0
                color: root.palette.text
                font.bold: true
                wrapMode: Text.WordWrap
                Accessible.name: text
            }
            Label {
                Layout.fillWidth: true
                text: backend.statusMessage || (backend.projectRoot ? "Ready" : "Open a project to begin.")
                elide: Text.ElideRight
                Accessible.name: "Status: " + text
            }
        }
    }
}
