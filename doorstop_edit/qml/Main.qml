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
    property string pendingPanel: ""
    readonly property var validationGraph: backend.appGraph || ({})
    readonly property var validationRun: validationGraph.validationRun || ({})
    readonly property var validationFindings: {
        const result = []
        const nodes = validationGraph.nodes || []
        for (let i = 0; i < nodes.length; ++i)
            if (nodes[i].type === "ValidationFinding") result.push(nodes[i])
        return result
    }
    readonly property int validationErrors: validationFindings.filter(function(n) { return n.severity === "error" }).length
    readonly property int validationWarnings: validationFindings.filter(function(n) { return n.severity === "warning" }).length
    readonly property bool validationOutdated: validationFindings.some(function(n) { return n.state === "stale" })
    function validationCount(count, singular, plural) {
        return count + " " + (count === 1 ? singular : plural)
    }
    readonly property string validationSummary: {
        if (!backend.projectRoot) return "Open a project to validate."
        const state = validationRun.state || "notRun"
        const label = state === "notRun" ? "Not yet validated" : state === "running" ? "Validation running…"
                    : state === "failed" ? "Validation failed" : "Validation complete"
        return label + " · " + validationCount(validationErrors, "error", "errors") + " · "
               + validationCount(validationWarnings, "warning", "warnings")
               + (validationOutdated ? " · Prior findings outdated" : "")
    }

    function openPendingPanel() {
        const next = pendingPanel
        pendingPanel = ""
        if (next === "graph") graphDrawer.open()
        else if (next === "validation") validationDrawer.open()
    }

    function toggleGraph() {
        if (graphDrawer.opened) {
            graphDrawer.close()
        } else {
            const focused = root.activeFocusItem
            graphDrawer.returnFocusItem = focused && focused.activeFocusOnTab
                                         ? focused : graphToggleButton
            if (validationDrawer.visible) {
                pendingPanel = "graph"
                validationDrawer.close()
            } else graphDrawer.open()
        }
    }

    function toggleValidation() {
        if (validationDrawer.opened) {
            validationDrawer.close()
        } else {
            const focused = root.activeFocusItem
            validationDrawer.returnFocusItem = focused && focused.activeFocusOnTab
                                              ? focused : validationSummaryButton
            if (graphDrawer.visible) {
                pendingPanel = "validation"
                graphDrawer.close()
            } else validationDrawer.open()
        }
    }

    function findingItem(uid) {
        if (!uid) return null
        const nodes = validationGraph.nodes || []
        for (let i = 0; i < nodes.length; ++i)
            if (nodes[i].type === "Item" && nodes[i].uid === uid) return nodes[i]
        return null
    }

    function openFinding(finding) {
        const item = finding && findingItem(finding.itemUid)
        if (item) openGraphNode(item, validationDrawer)
    }

    function openGraphNode(node, sourceDrawer) {
        if (!node || (node.type !== "Item" && node.type !== "Document"))
            return
        const drawer = sourceDrawer || graphDrawer
        const prefix = node.type === "Document" ? node.prefix
                        : String(node.documentId || "").replace(/^document:/, "")
        if (!prefix)
            return
        confirmLeaving(function() {
            // Synchronize the original lists, then use the existing backend selection path.
            const documents = backend.documents || []
            for (let i = 0; i < documents.length; ++i) {
                if (documents[i].prefix === prefix) {
                    documentList.currentIndex = i
                    break
                }
            }
            if (selectedDocumentPrefix !== prefix || node.type === "Document") {
                selectedDocumentPrefix = prefix
                itemList.currentIndex = -1
                backend.selectDocument(prefix)
            }
            if (node.type === "Item") {
                const items = backend.items || []
                for (let i = 0; i < items.length; ++i) {
                    if (items[i].uid === node.uid) {
                        itemList.currentIndex = i
                        break
                    }
                }
                backend.selectItem(node.uid)
            }
            drawer.navigatingToEditor = true
            drawer.navigationFocusTarget = node.type === "Item" ? headerField : documentList
            drawer.close()
        })
    }
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

    Shortcut {
        sequence: "Ctrl+G"
        context: Qt.ApplicationShortcut
        onActivated: root.toggleGraph()
    }

    Shortcut {
        sequence: "Escape"
        context: Qt.WindowShortcut
        enabled: graphDrawer.opened || validationDrawer.opened
        onActivated: {
            if (validationDrawer.opened) validationDrawer.close()
            else graphDrawer.close()
        }
    }

    Drawer {
        id: graphDrawer
        objectName: "graphDrawer"
        edge: Qt.RightEdge
        modal: false
        interactive: false
        width: Math.min(root.width - 12, 680)
        height: root.height
        padding: 0
        property var returnFocusItem: null
        property bool navigatingToEditor: false
        property var navigationFocusTarget: null
        onOpened: graphExplorer.focusSearch()
        onClosed: {
            if (root.pendingPanel) {
                returnFocusItem = null
                root.openPendingPanel()
                return
            }
            const destination = returnFocusItem
            const openingEditor = navigatingToEditor
            const editorTarget = navigationFocusTarget
            navigatingToEditor = false
            navigationFocusTarget = null
            returnFocusItem = null
            // Popup restores its focus after emitting closed. Restore our
            // previous control on the next event-loop turn instead.
            Qt.callLater(function() {
                if (graphDrawer.opened) return
                if (openingEditor) {
                    if (editorTarget && editorTarget.enabled)
                        editorTarget.forceActiveFocus()
                    else
                        graphToggleButton.forceActiveFocus()
                    return
                }
                if (destination && destination !== root
                        && destination.visible && destination.enabled)
                    destination.forceActiveFocus()
                else
                    graphToggleButton.forceActiveFocus()
            })
        }
        GraphExplorer {
            id: graphExplorer
            objectName: "graphExplorer"
            anchors.fill: parent
            active: graphDrawer.opened
            initialDocumentPrefix: root.selectedDocumentPrefix
            graph: active ? (backend.appGraph || ({})) : ({})
            onCloseRequested: graphDrawer.close()
            onActivateNode: function(node) { root.openGraphNode(node) }
        }
    }

    Drawer {
        id: validationDrawer
        objectName: "validationDrawer"
        edge: Qt.RightEdge
        modal: false
        interactive: false
        width: Math.min(root.width - 12, 540)
        height: root.height
        padding: 0
        property var returnFocusItem: null
        property bool navigatingToEditor: false
        property var navigationFocusTarget: null
        onOpened: validationList.forceActiveFocus()
        onClosed: {
            if (root.pendingPanel) {
                returnFocusItem = null
                root.openPendingPanel()
                return
            }
            const destination = returnFocusItem
            const openingEditor = navigatingToEditor
            const editorTarget = navigationFocusTarget
            returnFocusItem = null
            navigatingToEditor = false
            navigationFocusTarget = null
            Qt.callLater(function() {
                if (validationDrawer.opened || graphDrawer.opened) return
                if (openingEditor && editorTarget && editorTarget.enabled)
                    editorTarget.forceActiveFocus()
                else if (destination && destination !== root && destination.visible && destination.enabled)
                    destination.forceActiveFocus()
                else validationSummaryButton.forceActiveFocus()
            })
        }
        background: Rectangle { color: "#14202b"; border.color: "#55717a"; border.width: 1 }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: "VALIDATION  /  RESULTS"
                    font.family: "DejaVu Sans Mono"
                    font.pixelSize: 16
                    font.bold: true
                    color: "#7ddac4"
                }
                Button {
                    objectName: "validationCloseButton"
                    text: "Back to editor ✕"
                    Accessible.name: "Close validation results and return to editor"
                    onClicked: validationDrawer.close()
                }
            }
            Label {
                Layout.fillWidth: true
                text: root.validationSummary
                color: root.validationRun.state === "failed" || root.validationErrors ? "#ffc39f" : "#b4cbd0"
                font.bold: true
                wrapMode: Text.WordWrap
                Accessible.name: text
            }
            Label {
                Layout.fillWidth: true
                visible: root.validationOutdated
                text: "Prior findings are outdated. Project content changed since that run; validate again for current results."
                color: "#f4d590"
                wrapMode: Text.WordWrap
                Accessible.name: text
            }
            Label {
                Layout.fillWidth: true
                visible: root.validationRun.state === "failed"
                text: root.validationRun.error ? "Validation error: " + root.validationRun.error
                                               : "Validation could not complete. Try again."
                color: "#ffc39f"
                wrapMode: Text.WordWrap
                Accessible.name: text
            }
            Label {
                Layout.fillWidth: true
                visible: root.validationRun.state === "succeeded" && root.validationFindings.length === 0
                text: "No findings."
                color: "#7ddac4"
                Accessible.name: text
            }
            Label {
                Layout.fillWidth: true
                visible: root.validationRun.state === "notRun" && root.validationFindings.length === 0
                text: "Run validation to see findings here."
                color: "#b4cbd0"
                Accessible.name: text
            }
            Label {
                Layout.fillWidth: true
                visible: root.validationRun.state === "running" && root.validationFindings.length === 0
                text: "Checking project…"
                color: "#b4cbd0"
                Accessible.name: text
            }
            ListView {
                id: validationList
                objectName: "validationResultsList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                activeFocusOnTab: true
                keyNavigationWraps: true
                model: root.validationFindings
                Accessible.role: Accessible.List
                Accessible.name: "Validation findings. Use arrow keys to select; Enter or Space opens an item finding."
                Keys.onReturnPressed: if (currentItem) currentItem.activate()
                Keys.onEnterPressed: if (currentItem) currentItem.activate()
                Keys.onSpacePressed: if (currentItem) currentItem.activate()
                Keys.onEscapePressed: validationDrawer.close()
                delegate: ItemDelegate {
                    id: findingRow
                    objectName: "validationFindingRow"
                    readonly property var finding: modelData
                    readonly property bool itemFinding: !!root.findingItem(finding.itemUid)
                    width: validationList.width
                    height: Math.max(78, findingContent.implicitHeight + 20)
                    activeFocusOnTab: false
                    Accessible.role: Accessible.ListItem
                    Accessible.name: finding.severity + (finding.itemUid ? ", " + finding.itemUid : ", project")
                                     + ": " + finding.message + (finding.state === "stale" ? ", outdated" : "")
                    Accessible.description: itemFinding ? "Enter or Space opens this item in the editor."
                                            : finding.itemUid ? "Item unavailable; details only."
                                            : "Project-level finding; details only."
                    function activate() { if (itemFinding) root.openFinding(finding) }
                    onClicked: {
                        validationList.currentIndex = index
                        validationList.forceActiveFocus()
                        activate()
                    }
                    background: Rectangle {
                        color: validationList.currentIndex === index ? "#236a68" : "#21333e"
                        radius: 4
                        border.width: validationList.activeFocus && validationList.currentIndex === index ? 2 : 0
                        border.color: "#ffffff"
                    }
                    contentItem: ColumnLayout {
                        id: findingContent
                        spacing: 4
                        Label {
                            Layout.fillWidth: true
                            text: findingRow.finding.severity.toUpperCase()
                                  + "  ·  " + (findingRow.finding.itemUid || "Project")
                                  + (findingRow.finding.state === "stale" ? "  ·  OUTDATED" : "")
                            font.bold: true
                            color: findingRow.finding.severity === "error" ? "#ffc39f"
                                 : findingRow.finding.severity === "warning" ? "#f4d590" : "#7ddac4"
                        }
                        Label {
                            Layout.fillWidth: true
                            text: findingRow.finding.message
                            color: "#e8f1f2"
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
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
            RowLayout {
                Button {
                    objectName: "browseButton"
                    text: "Browse…"
                    Accessible.name: "Choose project folder"
                    onClicked: root.confirmLeaving(function() { backend.openProjectPicker() })
                }
                Button {
                    id: graphToggleButton
                    objectName: "graphToggleButton"
                    text: graphDrawer.opened ? "Close graph" : "Graph"
                    Accessible.name: graphDrawer.opened ? "Close graph, Ctrl+G" : "Explore project graph, Ctrl+G"
                    onClicked: root.toggleGraph()
                }
            }
        }

        RowLayout {
            objectName: "validationControls"
            Layout.fillWidth: true
            spacing: 8
            Button {
                objectName: "validateProjectButton"
                text: "Validate project"
                enabled: !!backend.projectRoot && root.validationRun.state !== "running"
                Accessible.name: "Validate project"
                onClicked: backend.requestValidation()
            }
            Button {
                id: validationSummaryButton
                objectName: "validationSummaryButton"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.validationSummary + "  ›"
                enabled: !!backend.projectRoot
                Accessible.name: "Show validation results. " + root.validationSummary
                onClicked: root.toggleValidation()
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
