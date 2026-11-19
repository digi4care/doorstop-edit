import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtWebEngine 1.15

// ItemRenderer - Document rendering component with QWebEngineView
// Equivalent to: doorstop_edit/item_renderer.py (Qt Widgets version)
// Slice 4: Document Renderer & Navigation

Rectangle {
    id: itemRenderer
    color: "#ffffff"
    border.color: "#ddd"
    
    // QML Model reference (from Python backend)
    property var rendererModel: null
    property bool isRendering: false
    property int progressValue: 0
    property string viewMode: "document"
    property string currentDocument: ""
    
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 0
        
        // Top toolbar with view controls and search
        Rectangle {
            Layout.preferredHeight: 40
            color: "#f5f5f5"
            border.color: "#ddd"
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                
                // View mode selector
                Label { 
                    text: "View:"; 
                    font.bold: true
                }
                
                ComboBox {
                    id: viewModeCombo
                    model: ["Document", "Section", "Item"]
                    currentIndex: 0
                    
                    onCurrentTextChanged: {
                        var mode = currentText.toLowerCase()
                        itemRenderer.viewMode = mode
                        if (rendererModel) {
                            rendererModel.setViewMode(mode)
                        }
                    }
                }
                
                Label { text: "|" }
                
                // Document selector (simplified for now)
                Label { 
                    text: "Document:"; 
                    font.bold: true
                }
                
                Label { 
                    id: currentDocLabel
                    text: itemRenderer.currentDocument || "None selected"
                    color: "#0066cc"
                    Layout.minimumWidth: 120
                }
                
                Spacer { Layout.fillWidth: true }
                
                // Search box
                TextField {
                    id: searchBox
                    placeholderText: "Search in document..."
                    width: 150
                    Layout.minimumWidth: 100
                    
                    onTextChanged: {
                        if (rendererModel && text.length > 0) {
                            rendererModel.setSearchQuery(text)
                        }
                    }
                }
                
                Button {
                    text: "Find"
                    enabled: searchBox.text.length > 0
                    onClicked: {
                        if (rendererModel) {
                            rendererModel.setSearchQuery(searchBox.text)
                        }
                    }
                }
            }
        }

        // Main rendering area with progress overlay
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "#ffffff"
            
            // WebEngine view for Markdown rendering
            WebEngineView {
                id: webView
                anchors.fill: parent
                
                // Load HTML content when rendering completes
                onLoadingChanged: function(loadRequest) {
                    if (loadRequest.status === WebEngineView.LoadSucceededStatus) {
                        console.log("Document rendered successfully")
                    }
                }
                
                // JavaScript console messages for debugging
                onJavaScriptConsoleMessage: function(level, message, lineNumber, sourceID) {
                    console.log("JS [" + level + "]: " + message)
                }
            }
            
            // Progress overlay (shown during rendering)
            Rectangle {
                id: progressOverlay
                anchors.fill: parent
                color: "#f0f0f0"
                visible: itemRenderer.isRendering
                opacity: 0.9
                
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 12
                    
                    Label { 
                        text: "Rendering document..."
                        font.bold: true
                        font.pixelSize: 14
                    }
                    
                    ProgressBar {
                        id: progressBar
                        width: 200
                        from: 0
                        to: 100
                        value: itemRenderer.progressValue
                    }
                    
                    Label { 
                        text: itemRenderer.progressValue + "%"
                        color: "#666"
                    }
                }
            }
            
            // Empty state overlay
            Rectangle {
                id: emptyStateOverlay
                anchors.fill: parent
                color: "#fafafa"
                visible: !itemRenderer.isRendering && itemRenderer.currentDocument === ""
                
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 8
                    
                    Label { 
                        text: "📄"
                        font.pixelSize: 48
                    }
                    
                    Label { 
                        text: "No document selected"
                        font.bold: true
                        font.pixelSize: 16
                    }
                    
                    Label { 
                        text: "Select a document from the tree view"
                        color: "#888"
                    }
                }
            }
            
            // Search results overlay
            Rectangle {
                id: searchResultsOverlay
                anchors.fill: parent
                color: "#fff3cd"
                visible: false
                opacity: 0.9
                
                property int currentResultIndex: 0
                property var searchResults: []
                
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 12
                    
                    Label { 
                        text: "Search Results"
                        font.bold: true
                        font.pixelSize: 14
                    }
                    
                    Label { 
                        id: searchResultCount
                        text: "Found " + searchResultsOverlay.searchResults.length + " matches"
                    }
                    
                    RowLayout {
                        Button {
                            text: "Previous"
                            enabled: searchResultsOverlay.currentResultIndex > 0
                            onClicked: {
                                if (searchResultsOverlay.currentResultIndex > 0) {
                                    searchResultsOverlay.currentResultIndex--
                                }
                            }
                        }
                        
                        Label { 
                            text: (searchResultsOverlay.currentResultIndex + 1) + " of " + searchResultsOverlay.searchResults.length 
                        }
                        
                        Button {
                            text: "Next"
                            enabled: searchResultsOverlay.currentResultIndex < searchResultsOverlay.searchResults.length - 1
                            onClicked: {
                                if (searchResultsOverlay.currentResultIndex < searchResultsOverlay.searchResults.length - 1) {
                                    searchResultsOverlay.currentResultIndex++
                                }
                            }
                        }
                    }
                    
                    Button {
                        text: "Close Search"
                        onClicked: {
                            searchResultsOverlay.visible = false
                            searchBox.text = ""
                        }
                    }
                }
            }
        }

        // Status bar
        Rectangle {
            Layout.preferredHeight: 25
            color: "#e8e8e8"
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 4
                
                Label { 
                    id: statusLabel
                    text: "Ready"
                    font.pixelSize: 10
                }
                
                Spacer { Layout.fillWidth: true }
                
                Label { 
                    text: "View: " + itemRenderer.viewMode
                    font.pixelSize: 10
                    color: "#666"
                }
            }
        }
    }

    // Signals for QML integration
    signal documentLoaded(string documentId)
    signal itemViewed(string itemId)
    signal linkClicked(string url)

    // Connect model signals to QML
    Connections {
        target: itemRenderer.rendererModel
        
        function onRender_progress_changed(progress) {
            itemRenderer.progressValue = progress
            itemRenderer.isRendering = progress < 100
            statusLabel.text = "Rendering... " + progress + "%"
        }
        
        function onRender_completed() {
            itemRenderer.isRendering = false
            statusLabel.text = "Render complete"
            itemRenderer.documentLoaded(itemRenderer.currentDocument)
        }
        
        function onView_mode_changed(mode) {
            itemRenderer.viewMode = mode
        }
        
        function onSearch_requested(query) {
            // In real implementation, this would highlight matches in webView
            console.log("Search requested:", query)
        }
    }

    // Load document from Python context
    function loadDocument(docId) {
        if (rendererModel && docId) {
            itemRenderer.currentDocument = docId
            rendererModel.renderDocument(docId)
            console.log("Loading document:", docId)
        } else {
            console.log("Warning: No renderer model or document ID provided")
        }
    }

    // Render HTML content directly
    function renderHtmlContent(htmlContent) {
        if (webView) {
            webView.loadHtml(htmlContent)
            console.log("HTML content rendered")
        }
    }

    Component.onCompleted: {
        console.log("ItemRenderer initialized")
        // Set default HTML content
        renderHtmlContent("<html><body><h1>Doorstop Document</h1><p>Select a document to render</p></body></html>")
    }
}
