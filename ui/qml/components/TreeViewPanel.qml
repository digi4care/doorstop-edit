import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// TreeViewPanel - Document/Item tree view component
// Equivalent to: doorstop_edit/item_tree_view.py (Qt Widgets version)
// Slice 2: Tree View Integration

Rectangle {
    id: treeViewPanel
    color: "#f8f8f8"
    border.color: "#ddd"
    
    // QML Model reference (from Python backend)
    property var modelRef: null
    
    // Filter state
    property string filterText: ""
    property bool showInactiveItems: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 4
        
        // Top toolbar with view controls and search
        Rectangle {
            Layout.preferredHeight: 50
            color: "white"
            border.color: "#ddd"
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                
                Label { text: "Tree View"; font.bold: true }
                
                Spacer { Layout.fillWidth: true }
                
                // View mode selector (Document/Section/Item) - QML ComboBox
                Rectangle {
                    width: 80; height: 25
                    color: "#e0e0e0"
                    
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        
                        text: "Mode: Item"
                    }
                }

                Label { text: "|" }
                
                // Search box with filter input
                TextField {
                    id: searchBox
                    placeholderText: "Filter..."
                    width: 120
                    Layout.minimumWidth: 80
                    
                    onTextChanged: {
                        treeViewPanel.filterText = text
                        if (modelRef) {
                            modelRef.setFilterText(text)
                        }
                    }
                    
                    Component.onCompleted: {
                        // Connect to Python model for filter updates
                        focus = false
                    }
                }

                Label { text: "|" }
                
                // Show/Hide inactive items checkbox
                CheckBox {
                    id: showInactiveCheckbox
                    text: "Show closed"
                    checked: treeViewPanel.showInactiveItems
                    
                    onCheckedChanged: {
                        treeViewPanel.showInactiveItems = checked
                        if (modelRef) {
                            modelRef.setShowInactive(checked)
                        }
                    }
                }
            }
        }

        // Tree view table area
        TableView {
            id: tableView
            Layout.fillWidth: true
            Layout.fillHeight: true
            
            // Model binding - will be set from Python context
            model: treeViewPanel.modelRef
            
            // Define columns for Doorstop tree structure
            columnConfig: [
                { "id": "id", "title": "ID", "width": 60, "role": "id" },
                { "id": "title", "title": "Title", "width": 250, "role": "title" },
                { "id": "status", "title": "Status", "width": 70, "role": "status" },
                { "id": "priority", "title": "Priority", "width": 60, "role": "priority" }
            ]

            // Item delegate with styling and context menu support
            delegate: ItemDelegate {
                width: tableView.width
                
                contentItem: RowLayout {
                    spacing: 8
                    
                    Label { text: model.id; font.bold: true }
                    
                    Label { 
                        text: model.title || "Untitled"
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    
                    Rectangle {
                        width: 60
                        height: 15
                        color: model.status === 'closed' ? "#ffcfcf" : 
                               (model.status === 'active' ? "#cfcfec" : "#fcfce2")
                        
                        Label { 
                            text: model.status || "?"
                            font.pixelSize: 9
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                    
                    Label { 
                        text: model.priority || "?"
                        width: 50
                    }
                }
                
                background: Rectangle {
                    color: mouseArea.pressed ? "#d0d0d0" : 
                           (mouseArea.containsMouse ? "#f0f0f0" : "transparent")
                }
                
                // Context menu support via MouseArea
                MouseArea {
                    id: mouseArea
                    anchors.fill: parent
                    
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    
                    // Left-click selection
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.LeftButton) {
                            console.log("Item selected:", model.id, model.title)
                            treeViewPanel.itemSelected.emit(model.id, model.title)
                        }
                        
                        // Right-click opens context menu
                        if (mouse.button === Qt.RightButton) {
                            contextMenu.open()
                        }
                    }
                    
                    doubleClicked: function(mouse) {
                        console.log("Item double-clicked:", model.id)
                    }
                }

                // Context menu for item actions
                Menu {
                    id: contextMenu
                    y: parent.height
                    
                    Action { text: "Open Item"; onTriggered: console.log("Open item") }
                    Action { text: "Edit Item"; onTriggered: console.log("Edit item") }
                    separator {}
                    Action { text: "Pin This Item"; onTriggered: console.log("Pin item") }
                    Action { text: "Expand All"; onTriggered: console.log("Expand all") }
                    Action { text: "Collapse All"; onTriggered: console.log("Collapse all") }
                }
            }

            // Column definition component for TableView
            Component {
                id: columnComponent
                TableViewColumn { role: "id"; title: "ID"; width: 60 }
                TableViewColumn { role: "title"; title: "Title"; width: 250 }
                TableViewColumn { role: "status"; title: "Status"; width: 70 }
                TableViewColumn { role: "priority"; title: "Priority"; width: 60 }
            }

            onItemActivated: function(index, column) {
                console.log("Activated item:", model.id)
            }
        }

        // Status bar area
        Rectangle {
            Layout.preferredHeight: 20
            color: "#e8e8e8"
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 4
                
                Label { id: itemCountLabel; text: "Items: 0"; font.pixelSize: 10 }
                
                Spacer { Layout.fillWidth: true }
                
                ProgressBar {
                    id: filterProgress
                    visible: false
                    height: 15
                    minimumValue: 0
                    maximumValue: 100
                    width: 80
                }
            }
        }
    }

    // Signal emitted when item is selected (to connect to QML)
    signal itemSelected(var itemId, var title)
    
    // Signal for document selection  
    signal documentSelected(var docId)
    
    // Signal for refresh request
    signal refreshRequested()
    
    // Method to load model from Python context
    function loadModelFromContext(contextProperty) {
        if (contextProperty) {
            treeViewPanel.modelRef = contextProperty
            console.log("Tree model loaded:", contextProperty.items().length, "items")
            
            // Update item count display
            itemCountLabel.text = "Items: " + contextProperty.items().length
        } else {
            console.log("Warning: No model reference provided for TreeViewPanel")
        }
    }

    Component.onCompleted: {
        console.log("TreeViewPanel initialized")
        loadModelFromContext(treeViewPanel.modelRef)
    }
}
