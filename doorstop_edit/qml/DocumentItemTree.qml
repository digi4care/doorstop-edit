import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Host supplies a new snapshot object on refresh: {documents: [{prefix,
// parentPrefix?, items: [{uid, level, header, text?, active?, normative?,
// reviewed?, cleared?, changed?, findings?: [{severity, message}], loadError?}]}]}.
// parentPrefix is a document prefix, not a path. No source objects are mutated.
Pane {
    id: tree
    objectName: "documentItemTree"
    property var snapshot: ({ documents: [] })
    property string selectedDocumentPrefix: ""
    property string selectedItemUid: ""
    property bool showInactive: false
    property var visibleRows: []
    property var expanded: ({})
    property var branchIds: []
    signal refreshRequested()
    signal documentSelectionRequested(string prefix)
    signal itemSelectionRequested(string uid, string prefix)

    implicitWidth: 440
    implicitHeight: 500
    padding: 12
    palette.window: "#14202b"
    palette.text: "#e8f1f2"
    palette.base: "#243544"
    palette.button: "#293d4d"
    palette.buttonText: "#eef4f4"
    palette.highlight: "#7ddac4"
    background: Rectangle { color: "#14202b"; border.color: "#55717a" }

    onSnapshotChanged: rebuild()
    onShowInactiveChanged: rebuild()
    Component.onCompleted: rebuild()

    function words() {
        return searchField.text.trim().toLocaleLowerCase().split(/\s+/).filter(function(s) { return !!s })
    }
    function matches(item, prefix, terms) {
        const content = [prefix, item.uid, item.level, item.header, item.text]
            .map(function(v) { return v === undefined || v === null ? "" : String(v) })
            .join(" ").toLocaleLowerCase()
        return terms.every(function(term) { return content.indexOf(term) !== -1 })
    }
    function levelParts(level) {
        const parts = String(level || "").split(".").map(Number)
        if (parts.some(function(part) { return !Number.isInteger(part) || part < 0 })) return []
        if (parts.length && parts[parts.length - 1] === 0) parts.pop()
        return parts
    }
    function compareLevels(a, b) {
        const left = levelParts(a.level), right = levelParts(b.level)
        for (let i = 0; i < Math.min(left.length, right.length); ++i)
            if (left[i] !== right[i]) return left[i] - right[i]
        return left.length - right.length
    }
    function isExpanded(id) { return expanded[id] !== false }
    function setExpanded(id, value) {
        expanded = Object.assign({}, expanded, { [id]: value })
        rebuild()
    }
    function setAllExpanded(value) {
        const next = ({})
        if (!value)
            for (let i = 0; i < branchIds.length; ++i) next[branchIds[i]] = false
        expanded = next
        rebuild()
    }
    function rebuild() {
        const terms = words()
        const searching = terms.length > 0
        const docs = (snapshot && snapshot.documents) || []
        const nodes = [], lookup = ({}), roots = [], result = [], branches = []
        for (let d = 0; d < docs.length; ++d) {
            const doc = docs[d]
            if (!doc || !doc.prefix) continue
            const prefix = String(doc.prefix)
            const node = { id: "document:" + prefix, type: "document", prefix: prefix,
                           parentPrefix: doc.parentPrefix || "", children: [], items: [] }
            nodes.push(node)
            lookup[prefix] = node
            const source = (doc.items || []).slice().sort(compareLevels)
            const levels = ({})
            for (let i = 0; i < source.length; ++i) {
                const item = source[i]
                if (!item || !item.uid) continue
                const parts = levelParts(item.level)
                const key = parts.join(".")
                const row = { id: "item:" + prefix + ":" + String(item.uid), type: "item",
                              prefix: prefix, uid: String(item.uid), level: String(item.level || ""),
                              header: item.header === undefined || item.header === null ? "" : String(item.header),
                              text: item.text || "", active: item.active, normative: item.normative,
                              reviewed: item.reviewed, cleared: item.cleared, changed: item.changed === true,
                              findings: item.findings || [], loadError: item.loadError || "", children: [] }
                let parent = null
                for (let n = parts.length - 1; n > 0 && !parent; --n)
                    parent = levels[parts.slice(0, n).join(".")]
                if (parent) parent.children.push(row)
                else node.items.push(row)
                if (key) levels[key] = row
            }
        }
        for (let d = 0; d < nodes.length; ++d) {
            const node = nodes[d]
            const parent = lookup[node.parentPrefix]
            if (parent && parent !== node) parent.children.push(node)
            else roots.push(node)
        }
        const seen = ({})
        function visit(node, depth, open) {
            if (seen[node.id]) return false
            seen[node.id] = true
            const start = result.length
            const children = node.type === "document" ? node.items.concat(node.children) : node.children
            const hasChildren = children.length > 0
            if (hasChildren) branches.push(node.id)
            const display = Object.assign({}, node, { depth: depth, hasChildren: hasChildren })
            delete display.children
            delete display.items
            delete display.parentPrefix
            result.push(display)
            let childMatch = false
            for (let i = 0; i < children.length; ++i)
                if (visit(children[i], depth + 1, open && (searching || tree.isExpanded(node.id))))
                    childMatch = true
            const direct = node.type === "document"
                ? terms.every(function(term) { return node.prefix.toLocaleLowerCase().indexOf(term) !== -1 })
                : (tree.showInactive || node.active !== false) && !node.loadError
                    && tree.matches(node, node.prefix, terms)
            const invalid = node.type === "item" && !!node.loadError && !searching
            if (!(direct || childMatch || invalid)) {
                result.splice(start)
                return false
            }
            if (!open) result.splice(start)
            else if (node.type === "item" && !direct && !invalid) {
                // Hidden/filter-mismatched ancestors do not hide matching descendants.
                result.splice(start, 1)
                for (let j = start; j < result.length; ++j) result[j].depth--
            }
            return true
        }
        for (let i = 0; i < roots.length; ++i) visit(roots[i], 0, true)
        branchIds = branches
        visibleRows = result
    }
    function displayHeader(entry) {
        if (entry.normative === false && entry.level.endsWith(".0"))
            return String(entry.text || "").split(/\r?\n/)[0]
        return entry.header
    }
    function hasFinding(entry, severity) {
        return (entry.findings || []).some(function(f) { return f.severity === severity })
    }
    function statusText(entry) {
        if (entry.loadError) return qsTr("Unable to load item")
        const labels = []
        if (hasFinding(entry, "error")) labels.push(qsTr("Validation error"))
        else if (hasFinding(entry, "warning")) labels.push(qsTr("Validation warning"))
        if (entry.reviewed === false) labels.push(qsTr("Needs review"))
        if (entry.active === false) labels.push(qsTr("Inactive"))
        else if (entry.cleared === false) labels.push(qsTr("Suspect links"))
        if (entry.normative === true) labels.push(qsTr("Normative"))
        else if (entry.normative === false) labels.push(qsTr("Informative"))
        return labels.join(" · ")
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: qsTr("DOCUMENTS / ITEMS")
                font.family: "DejaVu Sans Mono"
                font.pixelSize: 14
                font.bold: true
                color: "#7ddac4"
            }
            Button {
                objectName: "treeRefresh"
                text: qsTr("Refresh")
                Accessible.name: qsTr("Request a fresh document and item tree")
                onClicked: tree.refreshRequested()
            }
        }
        TextField {
            id: searchField
            objectName: "treeSearch"
            Layout.fillWidth: true
            placeholderText: qsTr("Search UID, level, header or text")
            Accessible.name: qsTr("Search documents and items")
            Accessible.description: qsTr("Separate terms with spaces; all terms must match")
            onTextChanged: tree.rebuild()
        }
        RowLayout {
            Layout.fillWidth: true
            CheckBox {
                objectName: "treeShowInactive"
                text: qsTr("Show inactive")
                checked: tree.showInactive
                onToggled: tree.showInactive = checked
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "treeExpandAll"
                text: qsTr("Expand all")
                Accessible.name: qsTr("Expand all document and item rows")
                onClicked: tree.setAllExpanded(true)
            }
            Button {
                objectName: "treeCollapseAll"
                text: qsTr("Collapse all")
                Accessible.name: qsTr("Collapse all document and item rows")
                onClicked: tree.setAllExpanded(false)
            }
        }
        ListView {
            id: rowsView
            objectName: "treeRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: tree.visibleRows
            activeFocusOnTab: true
            keyNavigationWraps: true
            Accessible.role: Accessible.Tree
            Accessible.name: qsTr("Document and item tree")
            Keys.onReturnPressed: if (currentItem) currentItem.activate()
            Keys.onEnterPressed: if (currentItem) currentItem.activate()
            Keys.onSpacePressed: if (currentItem) currentItem.activate()
            Keys.onRightPressed: if (currentItem && currentItem.entry.hasChildren)
                                     tree.setExpanded(currentItem.entry.id, true)
            Keys.onLeftPressed: if (currentItem && currentItem.entry.hasChildren)
                                    tree.setExpanded(currentItem.entry.id, false)
            delegate: ItemDelegate {
                id: row
                objectName: "treeRow"
                required property var modelData
                required property int index
                readonly property var entry: modelData
                readonly property bool selected: entry.type === "document"
                    ? entry.prefix === tree.selectedDocumentPrefix && !tree.selectedItemUid
                    : entry.uid === tree.selectedItemUid && entry.prefix === tree.selectedDocumentPrefix
                width: rowsView.width
                height: 56
                highlighted: selected
                enabled: !entry.loadError
                Accessible.role: Accessible.TreeItem
                Accessible.name: entry.type === "document" ? qsTr("Document %1").arg(entry.prefix)
                    : qsTr("Item %1, level %2, %3").arg(entry.uid).arg(entry.level).arg(tree.displayHeader(entry))
                Accessible.description: entry.type === "item"
                    ? tree.statusText(entry) + (entry.loadError ? ": " + entry.loadError : "") : ""
                function activate() {
                    rowsView.currentIndex = index
                    rowsView.forceActiveFocus()
                    if (entry.type === "document") tree.documentSelectionRequested(entry.prefix)
                    else tree.itemSelectionRequested(entry.uid, entry.prefix)
                }
                onClicked: activate()
                background: Rectangle {
                    color: row.selected ? "#236a68" : (row.hovered ? "#293d4d" : "#21333e")
                    radius: 4
                    border.width: rowsView.activeFocus && rowsView.currentIndex === row.index ? 2 : 0
                    border.color: "#e8f1f2"
                }
                contentItem: RowLayout {
                    spacing: 6
                    Item { Layout.preferredWidth: row.entry.depth * 16; Layout.fillHeight: true }
                    ToolButton {
                        Layout.preferredWidth: 30
                        visible: row.entry.hasChildren
                        text: tree.isExpanded(row.entry.id) ? "▾" : "▸"
                        Accessible.name: tree.isExpanded(row.entry.id)
                            ? qsTr("Collapse %1").arg(row.entry.type === "document" ? row.entry.prefix : row.entry.uid)
                            : qsTr("Expand %1").arg(row.entry.type === "document" ? row.entry.prefix : row.entry.uid)
                        onClicked: tree.setExpanded(row.entry.id, !tree.isExpanded(row.entry.id))
                    }
                    Item { Layout.preferredWidth: 30; visible: !row.entry.hasChildren }
                    Rectangle {
                        Layout.preferredWidth: 4
                        Layout.fillHeight: true
                        color: row.entry.type === "document" ? "#7ddac4"
                             : row.entry.loadError || tree.hasFinding(row.entry, "error") ? "#ffc39f"
                             : row.entry.reviewed === false || (row.entry.active !== false && row.entry.cleared === false)
                               || tree.hasFinding(row.entry, "warning") ? "#f4d590"
                             : row.entry.active === false ? "#81939a"
                             : row.entry.normative === false ? "#58bafc" : "#7ddac4"
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Label {
                            Layout.fillWidth: true
                            text: row.entry.type === "document" ? row.entry.prefix
                                  : row.entry.level + "  ·  " + row.entry.uid
                            color: "#e8f1f2"
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            text: row.entry.type === "document" ? qsTr("Document")
                                : row.entry.loadError ? qsTr("Unable to load item")
                                : (row.entry.changed ? "• " : "") + tree.displayHeader(row.entry)
                            color: row.entry.active === false ? "#a2b1b7" : "#b4cbd0"
                            font.bold: row.entry.type === "item" && row.entry.normative === false
                                       && row.entry.level.endsWith(".0")
                            elide: Text.ElideRight
                        }
                    }
                    Label {
                        visible: row.entry.type === "item"
                        text: tree.statusText(row.entry)
                        color: "#b4cbd0"
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Layout.maximumWidth: 155
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            visible: rowsView.count === 0
            text: searchField.text.trim() ? qsTr("No matching documents or items.")
                  : qsTr("No documents to display.")
            color: "#b4cbd0"
        }
    }
}
