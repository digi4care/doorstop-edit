import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1200
    height: 800
    title: "Doorstop Edit"
    minimumWidth: 800
    minimumHeight: 600
    
    // Persistent state properties
    property variant savedGeometry: null
    property variant savedState: null
    
    // QML component instances (set from Python context)
    property var treeViewPanel: null
    property var itemEditorPanel: null  
    property var itemRenderer: null
    property var pinnedItemsPanel: null

   MenuBar {
        visible: true
        Menu { 
            title: "File"
            Action { text: "Open Folder..."; onTriggered: console.log("Open folder") }
            Action { text: "Settings..."; onTriggered: console.log("Settings") }
            Action { text: "Exit"; onTriggered: mainWindow.close() }
        }
        Menu { 
            title: "View"
            Action { text: "Show Document Tree"; onTriggered: console.log("Toggle tree") }
            Action { text: "Show Item Editor"; onTriggered: console.log("Toggle editor") }
            Action { text: "Show Pinned Items"; onTriggered: console.log("Toggle pinned") }
        }
    }

    // Three-panel layout (simplified - no resize handles for testing)
    RowLayout {
        anchors.fill: parent
        
        // Left panel: Document Tree (70% default width)
        Rectangle {
            id: treeDock
            Layout.preferredWidth: 300
            Layout.minimumWidth: 150
            Layout.maximumWidth: 800
            height: parent.height
            color: "#f5f5f5"
            border.color: "#ddd"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 4
                
                Label { text: "Document Tree"; font.bold: true }
                Rectangle { 
                    id: treeViewComponent
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: "white"
                    border.color: "#ccc"
                    
                    Label { 
                        text: "[TreeViewPanel]\nSelect an item"
                        anchors.centerIn: parent
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
        }

        // Center panel with vertical split (render + editor)
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            
            // Top: Document/Item Renderer
            Rectangle {
                id: renderDock
                Layout.preferredHeight: 400
                Layout.minimumHeight: 200
                
                color: "#f5f5f5"
                
                ColumnLayout {
                    anchors.fill: parent
                    
                    Label { text: "Document View"; font.bold: true }
                    
                    Rectangle { 
                        id: rendererComponent
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: "white"
                        
                        Label { 
                            text: "[ItemRenderer]\nDocument preview"
                            anchors.centerIn: parent
                            wrapMode: Text.WordWrap
                        }
                    }
                    
                    // Search bar overlay
                    Rectangle {
                        height: 30; width: parent.width
                        color: "white"; border.color: "#ccc"
                        
                        RowLayout {
                            anchors.fill: parent; anchors.margins: 4
                            
                            Label { text: "Find:" }
                            TextField { 
                                placeholderText: "Search..."
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }

            // Bottom: Item Editor dock
            Rectangle {
                id: editDock
                Layout.preferredHeight: 400
                Layout.minimumHeight: 200
                
                color: "#f5f5f5"
                
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    
                    Label { text: "Edit Item"; font.bold: true }
                    
                    Rectangle { 
                        id: itemEditorComponent
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: "white"
                        
                        Label { 
                            text: "[ItemEditorPanel]\nEdit description here"
                            anchors.centerIn: parent
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }

        // Right panel: Pinned Items
        Rectangle {
            id: pinnedDock
            Layout.preferredWidth: 250
            Layout.minimumWidth: 150
            Layout.maximumWidth: 400
            height: parent.height
            color: "#f5f5f5"
            
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 4
                
                Label { text: "Pinned Items"; font.bold: true }
                
                Rectangle { 
                    id: pinnedItemsComponent
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: "white"
                    
                    Label { 
                        text: "[PinnedItemsPanel]\nDrag items here"
                        anchors.centerIn: parent
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    // Geometry state management functions
    function saveWindowGeometry() {
        savedGeometry = mainWindow.saveGeometry()
        console.log("Saved geometry:", savedGeometry.hex())
    }

    function restoreWindowGeometry() {
        if (savedGeometry && savedGeometry.length > 0) {
            mainWindow.restoreGeometry(savedGeometry)
        }
    }

    Component.onCompleted: {
        restoreWindowGeometry()
        console.log("MainWindow initialized successfully")
    }

    onClosing: saveWindowGeometry()
}
