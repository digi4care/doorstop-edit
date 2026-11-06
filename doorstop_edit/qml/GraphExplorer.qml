import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Pane {
    id: explorer
    property bool active: false
    property var graph: ({})
    property var nodesById: ({})
    property var edgesByNode: ({})
    property var results: []
    property var mapNodes: []
    property var mapEdges: []
    property string focusId: ""
    property string focusPath: ""
    property string focusRelation: ""
    property var focusEdge: null
    property string lastProjectId: ""
    property string initialDocumentPrefix: ""
    property real mapZoom: 0.75
    readonly property var focusedNode: nodesById[focusId] || null
    readonly property var run: graph.validationRun || ({})
    signal closeRequested()
    signal activateNode(var node)

    objectName: "graphExplorerPane"
    padding: 12
    palette.window: "#14202b"
    palette.text: "#e8f1f2"
    palette.base: "#243544"
    palette.button: "#293d4d"
    palette.buttonText: "#eef4f4"
    palette.highlight: "#7ddac4"
    background: Rectangle {
        color: "#14202b"
        border.color: "#55717a"
        border.width: 1
    }

    // Index only while visible. The backend has already published the snapshot on project open.
    onGraphChanged: if (active) rebuild()

    function rebuild() {
        if (!active) return
        if (lastProjectId !== (graph.projectId || "")) {
            focusId = ""
            focusPath = ""
            focusRelation = ""
            focusEdge = null
            lastProjectId = graph.projectId || ""
        }
        const lookup = ({})
        const adjacency = ({})
        const ns = graph.nodes || []
        const es = graph.edges || []
        for (let i = 0; i < ns.length; i++) {
            lookup[ns[i].id] = ns[i]
            adjacency[ns[i].id] = []
        }
        for (let i = 0; i < es.length; i++) {
            const edge = es[i]
            if (adjacency[edge.sourceId]) adjacency[edge.sourceId].push(edge)
            if (edge.targetId !== edge.sourceId && adjacency[edge.targetId])
                adjacency[edge.targetId].push(edge)
        }
        nodesById = lookup
        edgesByNode = adjacency
        if (!focusId) {
            const selectedUid = (backend.selectedItem || ({})).uid
            if (selectedUid && lookup["item:" + selectedUid]) focusId = "item:" + selectedUid
            else if (initialDocumentPrefix && lookup["document:" + initialDocumentPrefix])
                focusId = "document:" + initialDocumentPrefix
        }
        updateResults()
    }

    function labelFor(node) {
        if (!node) return "Unknown node"
        if (node.type === "Project") return "Project"
        if (node.type === "Document") return node.prefix || node.id
        if (node.type === "ValidationFinding") return node.severity + ": " + node.message
        return node.uid || node.id
    }
    function statusFor(node) {
        if (!node) return "Unknown"
        if (node.type === "Item") {
            let state = node.loadState === "error" ? "Load error" : (node.reviewed || "Unknown review")
            if (node.active === false) state += " · inactive"
            for (const status of ["suspect", "unresolved", "unknown"])
                if (hasLinkStatus(node, status)) state += " · link " + status
            return state
        }
        if (node.type === "UnresolvedItem") return "Unresolved target"
        if (node.type === "ValidationFinding") return node.severity + " · " + node.state
        return node.type
    }
    function edgeLabel(edge) {
        if (edge.type === "linksTo") return "Link · " + edge.status
        if (edge.type === "childDocumentOf") return "Parent document"
        if (edge.type === "reportedFor") return "Finding · " + edge.status
        return edge.type === "containsItem" ? "Contains item" : "Contains document"
    }
    function hasLinkStatus(node, status) {
        const edges = edgesByNode[node.id] || []
        for (let i = 0; i < edges.length; i++)
            if (edges[i].type === "linksTo" && edges[i].status === status) return true
        return false
    }
    function hasFinding(node, severity, state) {
        if (node.type === "ValidationFinding")
            return (severity === "Any" || node.severity === severity)
                    && (state === "Any" || node.state === state)
        const edges = edgesByNode[node.id] || []
        for (let i = 0; i < edges.length; i++) {
            const edge = edges[i]
            if (edge.type !== "reportedFor" || edge.targetId !== node.id) continue
            const finding = nodesById[edge.sourceId]
            if (finding && (severity === "Any" || finding.severity === severity)
                    && (state === "Any" || finding.state === state)) return true
        }
        return false
    }
    function matches(node) {
        const q = searchField.text.trim().toLowerCase()
        const doc = documentField.text.trim().toLowerCase()
        const level = levelField.text.trim().toLowerCase()
        const text = [node.uid, node.header, node.prefix, node.message, node.path, node.documentId, node.type]
                .map(function(v) { return String(v === undefined || v === null ? "" : v) }).join(" ").toLowerCase()
        if (q && text.indexOf(q) < 0) return false
        const owningDocument = node.type === "Item" ? String(node.documentId || "").replace(/^document:/, "")
                             : node.type === "Document" ? String(node.prefix || "") : ""
        if (doc && owningDocument.toLowerCase().indexOf(doc) < 0) return false
        if (level && (node.type !== "Item" || String(node.level === undefined || node.level === null ? "" : node.level).toLowerCase().indexOf(level) < 0)) return false
        if (activeFilter.currentIndex && (node.type !== "Item" || node.active !== (activeFilter.currentIndex === 1))) return false
        if (normativeFilter.currentIndex && (node.type !== "Item" || node.normative !== (normativeFilter.currentIndex === 1))) return false
        if (derivedFilter.currentIndex && (node.type !== "Item" || node.derived !== (derivedFilter.currentIndex === 1))) return false
        if (reviewFilter.currentIndex && (node.type !== "Item" || String(node.reviewed) !== reviewFilter.currentText)) return false
        if (linkFilter.currentIndex && !hasLinkStatus(node, linkFilter.currentText)) return false
        if (findingFilter.currentIndex >= 3 && run.state !== findingFilter.currentText.replace("Run: ", ""))
            return false
        if ((severityFilter.currentIndex || (findingFilter.currentIndex > 0 && findingFilter.currentIndex < 3))
                && !hasFinding(node, severityFilter.currentIndex ? severityFilter.currentText : "Any",
                               findingFilter.currentIndex > 0 && findingFilter.currentIndex < 3
                                    ? findingFilter.currentText : "Any")) return false
        return true
    }
    function updateResults() {
        if (!active) return
        const ns = graph.nodes || []
        const matchesList = []
        const query = searchField.text.trim().toLowerCase()
        // Exact UID searches should navigate to the item, not also match
        // validation messages that merely mention the same UID.
        let exactUidId = ""
        if (query) {
            for (let i = 0; i < ns.length; i++) {
                if ((ns[i].type === "Item" || ns[i].type === "UnresolvedItem")
                        && String(ns[i].uid || "").toLowerCase() === query) {
                    exactUidId = ns[i].id
                    break
                }
            }
        }
        for (let i = 0; i < ns.length; i++) {
            if ((!exactUidId || ns[i].id === exactUidId) && matches(ns[i]))
                matchesList.push(ns[i])
        }
        results = matchesList
        if (!nodesById[focusId] || (matchesList.length && !matches(nodesById[focusId])))
            focusId = matchesList.length ? matchesList[0].id : ""
        if (!matchesList.length) focusId = ""
        updateMap()
    }
    function edgeAllowed(edge) {
        if (relationFilter.currentIndex === 1 && edge.type !== "linksTo") return false
        if (relationFilter.currentIndex === 2 && edge.type !== "containsItem"
                && edge.type !== "containsDocument" && edge.type !== "childDocumentOf") return false
        if (relationFilter.currentIndex === 3 && edge.type !== "reportedFor") return false
        return edge.type !== "linksTo" || !linkFilter.currentIndex || edge.status === linkFilter.currentText
    }
    function updateMap() {
        const focus = focusedNode
        if (!focus) { mapNodes = []; mapEdges = []; return }
        const visibleNodes = [{node: focus, x: 553, y: 470, relation: "Selected", path: "", edge: null}]
        const visibleEdges = []
        const seen = ({})
        seen[focus.id] = true
        const impact = directionFilter.currentIndex === 1 && focus.type === "Item"
        const queue = [{id: focus.id, path: labelFor(focus), depth: 0}]
        while (queue.length && visibleNodes.length < 25) {
            const current = queue.shift()
            const edges = edgesByNode[current.id] || []
            for (let i = 0; i < edges.length && visibleNodes.length < 25; i++) {
                const edge = edges[i]
                if (!edgeAllowed(edge)) continue
                if (impact && (edge.type !== "linksTo" || edge.targetId !== current.id)) continue
                const otherId = edge.sourceId === current.id ? edge.targetId : edge.sourceId
                const other = nodesById[otherId]
                if (!other || seen[otherId]) continue
                seen[otherId] = true
                const k = visibleNodes.length - 1
                const ring = Math.floor(k / 8)
                const angle = (k % 8) * Math.PI / 4 - Math.PI / 2 + ring * 0.22
                const radius = 205 + ring * 142
                visibleNodes.push({node: other, x: 553 + Math.cos(angle) * radius,
                                   y: 470 + Math.sin(angle) * radius,
                                   relation: edgeLabel(edge), edge: edge,
                                   path: impact ? labelFor(other) + " → " + current.path : ""})
                visibleEdges.push({sourceId: current.id, targetId: otherId, edge: edge})
                if (impact) queue.push({id: otherId, path: labelFor(other) + " → " + current.path,
                                        depth: current.depth + 1})
            }
        }
        mapNodes = visibleNodes
        mapEdges = visibleEdges
        lines.requestPaint()
    }
    function choose(node, relation, path, edge) {
        if (!node) return
        focusId = node.id
        focusRelation = relation || ""
        focusEdge = edge || null
        focusPath = path || ""
        updateMap()
        mapView.contentX = Math.max(0, Math.min(mapView.contentWidth - mapView.width,
                                             (630 * mapZoom) - mapView.width / 2))
        mapView.contentY = Math.max(0, Math.min(mapView.contentHeight - mapView.height,
                                             (510 * mapZoom) - mapView.height / 2))
    }
    function adjustZoom(amount) { mapZoom = Math.max(0.45, Math.min(1.5, mapZoom + amount)) }

    Timer { id: searchDelay; interval: 180; onTriggered: explorer.updateResults() }

    ColumnLayout {
        anchors.fill: parent
        spacing: 5
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: "GRAPH  /  EXPLORER"
                font.family: "DejaVu Sans Mono"
                font.pixelSize: 16
                font.bold: true
                color: "#7ddac4"
            }
            Button {
                objectName: "graphCloseButton"
                text: "Back to editor ✕"
                Accessible.name: "Close graph and return to document and item editor"
                onClicked: explorer.closeRequested()
            }
        }
        Label {
            objectName: "graphStatus"
            Layout.fillWidth: true
            text: !explorer.graph.projectId ? (backend.projectRoot ? "Loading project graph…" : "Open a project to explore its graph.")
                  : "Revision " + explorer.graph.contentRevision + "  ·  Graph " + explorer.graph.graphGeneration
                    + "  ·  Validation: " + (explorer.run.state || "notRun")
                    + (explorer.run.error ? " — " + explorer.run.error : "")
            color: explorer.run.state === "failed" ? "#ffc39f" : "#b4cbd0"
            elide: Text.ElideRight
            Accessible.name: text
        }
        TextField {
            id: searchField
            objectName: "graphSearchField"
            Layout.fillWidth: true
            placeholderText: "Search UID, header, document, finding…"
            Accessible.name: "Search graph by UID, header, document or finding"
            Accessible.description: "Press Down Arrow to jump to matching results; Tab moves through filters."
            onTextChanged: searchDelay.restart()
            Keys.onDownPressed: function(event) {
                // Use the latest typed text even if the short debounce has not fired yet.
                searchDelay.stop()
                explorer.updateResults()
                if (resultList.count > 0) {
                    resultList.currentIndex = 0
                    resultList.forceActiveFocus()
                    event.accepted = true
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: "RESULTS  /  Enter to focus · use Open in editor"
            font.family: "DejaVu Sans Mono"
            font.pixelSize: 11
            color: "#7ddac4"
        }
        FocusScope {
            id: resultList
            objectName: "graphResultsList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            activeFocusOnTab: true
            property alias count: resultViewport.count
            property alias currentIndex: resultViewport.currentIndex
            property alias currentItem: resultViewport.currentItem
            Accessible.name: "Graph search results. Up and Down select, Enter or Space focuses a node."
            Accessible.role: Accessible.List
            function step(direction) {
                if (count > 0)
                    currentIndex = (currentIndex + direction + count) % count
            }
            Keys.onDownPressed: function(event) { step(1); event.accepted = true }
            Keys.onUpPressed: function(event) { step(-1); event.accepted = true }
            Keys.onReturnPressed: if (currentItem) currentItem.activate()
            Keys.onEnterPressed: if (currentItem) currentItem.activate()
            Keys.onSpacePressed: if (currentItem) currentItem.activate()
            ListView {
                id: resultViewport
                anchors.fill: parent
                clip: true
                model: explorer.results
                activeFocusOnTab: false
                focus: false
                delegate: Item {
                    id: row
                    objectName: "graphResultRow"
                    readonly property var node: modelData
                    width: resultViewport.width
                    height: 51
                    // The results focus scope owns arrow/Enter/Space navigation; rows must not
                    // steal its Tab stop as separate controls.
                    activeFocusOnTab: false
                    focus: false
                    readonly property bool highlighted: node.id === explorer.focusId
                    Accessible.role: Accessible.ListItem
                    Accessible.description: resultList.currentIndex === index
                        ? "Current result. Enter or Space focuses this node; then use Open in editor."
                        : "Use Up or Down to select this result."
                    Accessible.name: explorer.labelFor(node) + ", " + explorer.statusFor(node)
                    function activate() {
                        resultList.currentIndex = index
                        explorer.choose(node)
                        resultList.forceActiveFocus()
                    }
                    Rectangle {
                        anchors.fill: parent
                        color: row.highlighted ? "#236a68" : "transparent"
                    }
                    Rectangle {
                        objectName: "graphResultFocusOutline"
                        anchors.fill: parent
                        anchors.margins: 2
                        z: 1
                        color: "transparent"
                        radius: 4
                        border.width: resultList.activeFocus && resultList.currentIndex === index ? 2 : 0
                        border.color: "#ffffff"
                    }
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 0
                        Label {
                            Layout.fillWidth: true
                            text: explorer.labelFor(row.node) + "  /  " + explorer.statusFor(row.node)
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            text: row.node.header || row.node.message || row.node.documentId || row.node.path || row.node.type
                            color: row.highlighted ? explorer.palette.highlightedText : "#b4cbd0"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: row.activate()
                    }
                }
            }
        }
        ScrollView {
            id: filterScroll
            objectName: "graphFilters"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(90, explorer.height * 0.16)
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            Flow {
                width: filterScroll.availableWidth
                spacing: 5
                TextField {
                    id: documentField
                    objectName: "graphDocumentFilter"
                    width: 105
                    placeholderText: "Document"
                    Accessible.name: "Filter by document prefix"
                    onTextChanged: searchDelay.restart()
                }
                TextField {
                    id: levelField
                    objectName: "graphLevelFilter"
                    width: 88
                    placeholderText: "Level"
                    Accessible.name: "Filter by level"
                    onTextChanged: searchDelay.restart()
                }
                ComboBox {
                    id: activeFilter
                    objectName: "graphActiveFilter"
                    width: 112
                    model: ["Active: any", "Active", "Inactive"]
                    Accessible.name: "Active status filter: " + currentText
                    onCurrentIndexChanged: searchDelay.restart()
                }
                ComboBox {
                    id: normativeFilter
                    objectName: "graphNormativeFilter"
                    width: 123
                    model: ["Norm: any", "Normative", "Informative"]
                    Accessible.name: "Normative status filter: " + currentText
                    onCurrentIndexChanged: searchDelay.restart()
                }
                ComboBox {
                    id: derivedFilter
                    objectName: "graphDerivedFilter"
                    width: 125
                    model: ["Derived: any", "Derived", "Not derived"]
                    Accessible.name: "Derived status filter: " + currentText
                    onCurrentIndexChanged: searchDelay.restart()
                }
                ComboBox {
                    id: reviewFilter
                    objectName: "graphReviewFilter"
                    width: 132
                    model: ["Review: any", "reviewed", "needsReview", "unknown"]
                    Accessible.name: "Review status filter: " + currentText
                    onCurrentIndexChanged: searchDelay.restart()
                }
                ComboBox {
                    id: linkFilter
                    objectName: "graphLinkFilter"
                    width: 140
                    model: ["Link: any", "suspect", "unresolved", "unknown", "ok"]
                    Accessible.name: "Link status filter: " + currentText
                    onCurrentIndexChanged: { searchDelay.restart(); explorer.updateMap() }
                }
                ComboBox {
                    id: severityFilter
                    objectName: "graphSeverityFilter"
                    width: 136
                    model: ["Severity: any", "error", "warning", "info"]
                    Accessible.name: "Validation severity filter: " + currentText
                    onCurrentIndexChanged: searchDelay.restart()
                }
                ComboBox {
                    id: findingFilter
                    objectName: "graphFindingStateFilter"
                    width: 144
                    model: ["Finding: any", "current", "stale", "Run: notRun", "Run: running", "Run: failed", "Run: succeeded"]
                    Accessible.name: "Validation finding state filter: " + currentText
                    onCurrentIndexChanged: searchDelay.restart()
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            ComboBox {
                id: directionFilter
                objectName: "graphDirectionFilter"
                Layout.fillWidth: true
                model: ["Direct neighbors", "Incoming impact · all levels"]
                Accessible.name: "Graph direction: " + currentText
                onCurrentIndexChanged: explorer.updateMap()
            }
            ComboBox {
                id: relationFilter
                objectName: "graphRelationFilter"
                Layout.fillWidth: true
                model: ["All relations", "Links", "Structure", "Findings"]
                Accessible.name: "Relation type: " + currentText
                onCurrentIndexChanged: explorer.updateMap()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: explorer.results.length + " matches  ·  " + Math.max(0, explorer.mapNodes.length - 1)
                      + " shown around selection" + (explorer.mapNodes.length === 25 ? " (first 24; refine search)" : "")
                elide: Text.ElideRight
                color: "#b4cbd0"
                Accessible.name: text
            }
            Button { objectName: "graphZoomOut"; text: "−"; Accessible.name: "Zoom out graph"; onClicked: explorer.adjustZoom(-0.15) }
            Label { text: Math.round(explorer.mapZoom * 100) + "%"; Accessible.name: "Graph zoom " + text }
            Button { objectName: "graphZoomIn"; text: "+"; Accessible.name: "Zoom in graph"; onClicked: explorer.adjustZoom(0.15) }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(110, explorer.height * 0.20)
            color: "#1b2c37"
            border.color: "#42626d"
            radius: 4
            clip: true
            Flickable {
                id: mapView
                objectName: "graphViewport"
                anchors.fill: parent
                contentWidth: 1260 * explorer.mapZoom
                contentHeight: 1020 * explorer.mapZoom
                boundsBehavior: Flickable.StopAtBounds
                clip: true
                activeFocusOnTab: true
                Accessible.name: "Graph map. Arrow keys pan, plus and minus zoom. Tab to focus nodes."
                Keys.onLeftPressed: contentX = Math.max(0, contentX - 60)
                Keys.onRightPressed: contentX = Math.min(contentWidth - width, contentX + 60)
                Keys.onUpPressed: contentY = Math.max(0, contentY - 60)
                Keys.onDownPressed: contentY = Math.min(contentHeight - height, contentY + 60)
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) {
                        explorer.adjustZoom(0.15); event.accepted = true
                    } else if (event.key === Qt.Key_Minus) {
                        explorer.adjustZoom(-0.15); event.accepted = true
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    onWheel: function(wheel) {
                        if (wheel.modifiers & Qt.ControlModifier) {
                            explorer.adjustZoom(wheel.angleDelta.y > 0 ? 0.1 : -0.1)
                            wheel.accepted = true
                        } else wheel.accepted = false
                    }
                }
                Item {
                    id: mapLayer
                    width: 1260
                    height: 1020
                    scale: explorer.mapZoom
                    transformOrigin: Item.TopLeft
                    Canvas {
                        id: lines
                        anchors.fill: parent
                        onPaint: {
                            const ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            const positions = ({})
                            for (let i = 0; i < explorer.mapNodes.length; i++) {
                                const entry = explorer.mapNodes[i]
                                positions[entry.node.id] = {x: entry.x + 77, y: entry.y + 42}
                            }
                            for (let i = 0; i < explorer.mapEdges.length; i++) {
                                const edge = explorer.mapEdges[i]
                                const start = positions[edge.sourceId], end = positions[edge.targetId]
                                if (!start || !end) continue
                                ctx.beginPath()
                                ctx.moveTo(start.x, start.y)
                                ctx.lineTo(end.x, end.y)
                                ctx.lineWidth = edge.edge.status === "suspect" ? 3 : 1.5
                                ctx.strokeStyle = edge.edge.status === "suspect" ? "#eaa078" : "#658e9c"
                                ctx.stroke()
                            }
                        }
                    }
                    Repeater {
                        model: explorer.mapNodes
                        delegate: Button {
                            id: card
                            objectName: "graphNodeCard"
                            readonly property var entry: modelData
                            x: entry.x
                            y: entry.y
                            width: 154
                            height: 84
                            activeFocusOnTab: true
                            text: explorer.labelFor(entry.node) + "\n" + explorer.statusFor(entry.node)
                            font.family: "DejaVu Sans Mono"
                            font.pixelSize: 11
                            Accessible.name: explorer.labelFor(entry.node) + ", " + explorer.statusFor(entry.node)
                                             + ", " + entry.relation
                                             + (entry.path ? ", path " + entry.path : "")
                            Accessible.description: "Select for details; open in editor with the button below."
                            background: Rectangle {
                                radius: 5
                                color: index === 0 ? "#236a68" : "#293f4b"
                                border.width: card.activeFocus || index === 0 ? 2 : 1
                                border.color: card.activeFocus ? "#ffffff" : index === 0 ? "#7ddac4" : "#638391"
                            }
                            onClicked: explorer.choose(entry.node, entry.relation, entry.path, entry.edge)
                            Keys.onReturnPressed: explorer.choose(entry.node, entry.relation, entry.path, entry.edge)
                            Keys.onEnterPressed: explorer.choose(entry.node, entry.relation, entry.path, entry.edge)
                        }
                    }
                }
                Component.onCompleted: {
                    contentX = Math.max(0, 630 * explorer.mapZoom - width / 2)
                    contentY = Math.max(0, 510 * explorer.mapZoom - height / 2)
                }
            }
            Label {
                anchors.centerIn: parent
                visible: explorer.mapNodes.length === 0
                text: !explorer.graph.projectId ? "Graph unavailable until a project opens."
                      : linkFilter.currentIndex ? "No links with this status match the filters."
                      : severityFilter.currentIndex || findingFilter.currentIndex
                        ? "No validation results match the filters. Check the run state above."
                      : "No matching nodes. Change the search or filters."
                color: "#eef4f4"
                wrapMode: Text.WordWrap
                width: parent.width - 24
                horizontalAlignment: Text.AlignHCenter
                Accessible.name: text
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 83
            color: "#21333e"
            radius: 4
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 7
                spacing: 2
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: explorer.focusedNode ? explorer.labelFor(explorer.focusedNode) + "  ·  " + explorer.statusFor(explorer.focusedNode) : "No selection"
                        font.bold: true
                        elide: Text.ElideRight
                        Accessible.name: "Selected graph node: " + text
                    }
                    Button {
                        objectName: "graphOpenInEditorButton"
                        text: explorer.focusedNode && explorer.focusedNode.type === "Document" ? "Open document ↗" : "Open in editor ↗"
                        enabled: explorer.focusedNode && (explorer.focusedNode.type === "Document" || explorer.focusedNode.type === "Item")
                        Accessible.name: text
                        onClicked: explorer.activateNode(explorer.focusedNode)
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: (explorer.focusPath || explorer.focusRelation || "Select a map node to inspect its relation.")
                          + (explorer.focusEdge && explorer.focusEdge.provenance
                             ? " · " + (explorer.focusEdge.provenance.sourcePath || explorer.focusEdge.provenance.sourceKey || "")
                               + (explorer.focusEdge.type === "linksTo"
                                  ? " · stored stamp: " + (explorer.focusEdge.provenance.storedLinkStamp || "unavailable")
                                    + " · target stamp: " + (explorer.focusEdge.provenance.currentTargetStamp || "unavailable") : "")
                             : "")
                    elide: Text.ElideRight
                    color: "#7ddac4"
                    Accessible.name: "Relation: " + text
                }
                Label {
                    Layout.fillWidth: true
                    text: explorer.focusedNode
                          ? (explorer.focusedNode.header || explorer.focusedNode.message || "")
                            + "  ·  Source: " + (explorer.focusedNode.provenance.sourcePath || explorer.focusedNode.provenance.sourceKind || "unknown")
                          : "Select a result or map node."
                    elide: Text.ElideRight
                    color: "#b4cbd0"
                    Accessible.name: text
                }
            }
        }

    }
}
