import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// PinnedItemsPanel - Pinned items management component
// Equivalent to: doorstop_edit/pinned_items_view.py (Qt Widgets version)
// Slice 5: Pinned Items & State Persistence

Rectangle {
    id: pinnedItemsPanel
    color: "#f0f8ff"
    border.color: "#ddd"
    
    // QML Model reference (from Python backend)
    property var pinnedModel: null
    property var pinnedItems: []
    property int pinnedCount: 0
    
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 4
        
        // Top toolbar with actions
        Rectangle {
            Layout.preferredHeight: 40
            color: "white"
            border.color: "#ddd"
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                
                Label { 
                    text: "Pinned Items"; 
                    font.bold: true
                }
                
                Label { 
                    text: "(" + pinnedItemsPanel.pinnedCount + ")"
                    color: "#666"
                }
                
                Spacer { Layout.fillWidth: true }
                
                // Add button with popup menu
                Button {
                    id: addButton
                    text: "+"
                    
                    onClicked: {
                        addMenu.open()
                    }
                    
                    Menu {
                        id: addMenu
                        y: parent.height
                        
                        Action { 
                            text: "Add from Tree View"
                            onTriggered: {
                                console.log("Add from tree view")
                                // In real implementation, this would open tree selection
                            }
                        }
                        
                        Action { 
                            text: "Import from File..."
                            onTriggered: {
                                console.log("Import pinned items from file")
                            }
                        }
                        
                        separator {}
                        
                        Action { 
                            text: "Clear All Pinned Items"
                            enabled: pinnedItemsPanel.pinnedCount > 0
                            onTriggered: {
                                if (pinnedItemsPanel.pinnedModel) {
                                    pinnedItemsPanel.pinnedModel.clearAllPinnedItems()
                                }
                            }
                        }
                    }
                }
                
                // Refresh button
                Button {
                    text: "Refresh"
                    onClicked: {
                        if (pinnedItemsPanel.pinnedModel) {
                            pinnedItemsPanel.pinnedModel.pinnedItems()
                            console.log("Pinned items refreshed")
                        }
                    }
                }
            }
        }

        // Pinned items list
        ListView {
            id: pinnedListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: pinnedItemsPanel.pinnedItems
            
            delegate: ItemDelegate {
                width: pinnedListView.width
                height: 40
                
                contentItem: RowLayout {
                    spacing: 8
                    
                    // Pin icon
                    Label { 
                        text: "📌"
                        font.pixelSize: 16
                    }
                    
                    // Item ID
                    Label { 
                        text: modelData.id || "Unknown"
                        font.bold: true
                        font.family: "Monospace"
                        color: "#0066cc"
                        Layout.minimumWidth: 80
                    }
                    
                    // Item title
                    Label { 
                        text: modelData.title || "No title"
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    
                    // Status indicator
                    Rectangle {
                        width: 60
                        height: 18
                        color: modelData.status === 'closed' ? "#ffcfcf" : 
                               (modelData.status === 'active' ? "#cfcfec" : "#fcfce2")
                        
                        Label { 
                            text: modelData.status || "?"
                            font.pixelSize: 10
                            horizontalAlignment: Text.AlignHCenter
                            anchors.centerIn: parent
                        }
                    }
                    
                    // Remove button
                    Button {
                        text: "×"
                        width: 20
                        height: 20
                        
                        onClicked: {
                            if (pinnedItemsPanel.pinnedModel && modelData.id) {
                                pinnedItemsPanel.pinnedModel.removePinnedItem(modelData.id)
                            }
                        }
                    }
                }
                
                background: Rectangle {
                    color: mouseArea.pressed ? "#d0d0d0" : 
                           (mouseArea.containsMouse ? "#f5f5f5" : "transparent")
                    border.color: "#eee"
                }
                
                // Context menu support
                MouseArea {
                    id: mouseArea
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    
                    onClicked: function(mouse) {
                        if (mouse.button === Qt.LeftButton) {
                            console.log("Pinned item selected:", modelData.id)
                            // In real implementation, this would open the item
                        }
                        
                        if (mouse.button === Qt.RightButton) {
                            itemContextMenu.open()
                        }
                    }
                }

                // Context menu for pinned item
                Menu {
                    id: itemContextMenu
                    y: parent.height
                    
                    Action { 
                        text: "Open Item"
                        onTriggered: console.log("Open pinned item:", modelData.id)
                    }
                    
                    Action { 
                        text: "Unpin Item"
                        onTriggered: {
                            if (pinnedItemsPanel.pinnedModel && modelData.id) {
                                pinnedItemsPanel.pinnedModel.removePinnedItem(modelData.id)
                            }
                        }
                    }
                    
                    separator {}
                    
                    Action { 
                        text: "Copy ID"
                        onTriggered: {
                            if (modelData.id) {
                                console.log("Copied to clipboard:", modelData.id)
                                // In real implementation, copy to clipboard
                            }
                        }
                    }
                }
            }

            // Empty state overlay
            Rectangle {
                anchors.fill: parent
                color: "#fafafa"
                visible: pinnedItemsPanel.pinnedCount === 0
                opacity: 0.8
                
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 8
                    
                    Label { 
                        text: "📌"
                        font.pixelSize: 48
                    }
                    
                    Label { 
                        text: "No pinned items"
                        font.bold: true
                        font.pixelSize: 14
                    }
                    
                    Label { 
                        text: "Pin items from the tree view for quick access"
                        color: "#888"
                        font.pixelSize: 11
                    }
                    
                    Button {
                        text: "Add from Tree View"
                        enabled: false  // Would be enabled when tree selection available
                        
                        onClicked: {
                            console.log("Add from tree view")
                        }
                    }
                }
            }
        }

        // Bottom status area
        Rectangle {
            Layout.preferredHeight: 20
            color: "#e8e8e8"
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 4
                
                Label { 
                    text: pinnedItemsPanel.pinnedCount + " items pinned"
                    font.pixelSize: 10
                }
                
                Spacer { Layout.fillWidth: true }
                
                Label { 
                    text: "Last updated: " + new Date().toLocaleTimeString()
                    font.pixelSize: 9
                    color: "#666"
                }
            }
        }
    }

    // Signals for QML integration
    signal itemPinned(string itemId)
    signal itemUnpinned(string itemId)
    signal itemsCleared()
    signal addRequested()

    // Connect model signals to QML
    Connections {
        target: pinnedItemsPanel.pinnedModel
        
        function onPinned_items_changed() {
            if (pinnedItemsPanel.pinnedModel) {
                pinnedItemsPanel.pinnedItems = pinnedItemsPanel.pinnedModel.pinnedItems()
                pinnedItemsPanel.pinnedCount = pinnedItemsPanel.pinnedItems.length
            }
        }
        
        function onItem_pinned(itemId) {
            pinnedItemsPanel.itemPinned(itemId)
        }
        
        function onItem_unpinned(itemId) {
            pinnedItemsPanel.itemUnpinned(itemId)
        }
        
        function onItems_cleared() {
            pinnedItemsPanel.itemsCleared()
            pinnedItemsPanel.pinnedItems = []
            pinnedItemsPanel.pinnedCount = 0
        }
    }

    // Load pinned items from Python context
    function loadPinnedItemsFromContext() {
        if (pinnedItemsPanel.pinnedModel) {
            pinnedItemsPanel.pinnedItems = pinnedItemsPanel.pinnedModel.pinnedItems()
            pinnedItemsPanel.pinnedCount = pinnedItemsPanel.pinnedItems.length
            console.log("Loaded", pinnedItemsPanel.pinnedCount, "pinned items")
        } else {
            console.log("Warning: No pinned model provided for PinnedItemsPanel")
        }
    }

    // Add pinned item manually
    function addPinnedItem(itemData) {
        if (pinnedItemsPanel.pinnedModel && itemData) {
            pinnedItemsPanel.pinnedModel.addPinnedItem(itemData)
        }
    }

    Component.onCompleted: {
        console.log("PinnedItemsPanel initialized")
        loadPinnedItemsFromContext()
    }
}
