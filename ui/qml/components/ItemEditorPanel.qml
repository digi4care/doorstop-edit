import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// ItemEditorPanel - Item editing component with validation
// Equivalent to: doorstop_edit/item_edit_view.py (Qt Widgets version)
// Slice 3: Item Editor Component

Rectangle {
    id: itemEditorPanel
    color: "#fafafa"
    border.color: "#ddd"
    
    // QML Model reference (from Python backend)
    property var editorModel: null
    property bool isDirty: false
    
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        
        // Top toolbar with UID display, save/undo buttons
        Rectangle {
            Layout.preferredHeight: 45
            color: "white"
            border.color: "#ddd"
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                
                // UID display
                Label { 
                    text: "UID:"; 
                    font.bold: true;
                    color: "#555"
                }
                Label { 
                    id: uidLabel
                    text: editorModel ? editorModel.getUid() : "No item loaded"
                    font.family: "Monospace"
                    color: "#0066cc"
                    Layout.minimumWidth: 80
                }
                
                // Save button
                Button {
                    id: saveButton
                    text: "Save"
                    enabled: itemEditorPanel.isDirty
                    
                    onClicked: {
                        if (editorModel) {
                            editorModel.saveItem()
                            console.log("Item saved")
                        }
                    }
                }
                
                // Undo button
                Button {
                    id: undoButton
                    text: "Undo"
                    enabled: itemEditorPanel.isDirty
                    
                    onClicked: {
                        if (editorModel) {
                            editorModel.undoChanges()
                            console.log("Changes undone")
                        }
                    }
                }
                
                Spacer { Layout.fillWidth: true }
                
                // Dirty state indicator (red dot)
                Rectangle {
                    id: dirtyIndicator
                    width: 12
                    height: 12
                    radius: 6
                    color: itemEditorPanel.isDirty ? "#ff4444" : "#cccccc"
                    visible: itemEditorPanel.isDirty
                    
                    ToolTip.visible: dirtyIndicatorMouseArea.containsMouse
                    ToolTip.text: itemEditorPanel.isDirty ? "Unsaved changes" : "No changes"
                    
                    MouseArea {
                        id: dirtyIndicatorMouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                    }
                }
                
                Label { 
                    text: itemEditorPanel.isDirty ? "Modified" : "Clean"
                    font.pixelSize: 10
                    color: itemEditorPanel.isDirty ? "#ff4444" : "#888"
                }
            }
        }

        // Main editing area - scrollable form
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            
            ColumnLayout {
                width: parent.width
                spacing: 12
                
                // Title field
                GroupBox {
                    title: "Item Details"
                    Layout.fillWidth: true
                    
                    GridLayout {
                        columns: 2
                        rowSpacing: 8
                        columnSpacing: 12
                        
                        Label { text: "Title:" }
                        TextField {
                            id: titleField
                            Layout.fillWidth: true
                            text: editorModel ? editorModel.getCurrentItemData().title : ""
                            placeholderText: "Enter item title"
                            
                            onTextChanged: {
                                if (editorModel) {
                                    editorModel.setFieldValue("title", text)
                                    // Validate on change
                                    editorModel.validateField("title")
                                }
                            }
                        }
                        
                        Label { text: "ID:" }
                        TextField {
                            id: idField
                            Layout.fillWidth: true
                            text: editorModel ? editorModel.getCurrentItemData().id : ""
                            placeholderText: "REQ-001"
                            readOnly: editorModel ? editorModel.getCurrentItemData().id.length > 0 : false
                            
                            onTextChanged: {
                                if (editorModel) {
                                    editorModel.setFieldValue("id", text)
                                    editorModel.validateField("id")
                                }
                            }
                        }
                        
                        Label { text: "Status:" }
                        ComboBox {
                            id: statusCombo
                            model: ["active", "closed", "draft", "review"]
                            currentIndex: editorModel ? 
                                (editorModel.getCurrentItemData().status === "closed" ? 1 :
                                 editorModel.getCurrentItemData().status === "draft" ? 2 :
                                 editorModel.getCurrentItemData().status === "review" ? 3 : 0) : 0
                            
                            onCurrentTextChanged: {
                                if (editorModel) {
                                    editorModel.setFieldValue("status", currentText)
                                }
                            }
                        }
                        
                        Label { text: "Priority:" }
                        ComboBox {
                            id: priorityCombo
                            model: ["high", "medium", "low"]
                            currentIndex: editorModel ? 
                                (editorModel.getCurrentItemData().priority === "medium" ? 1 :
                                 editorModel.getCurrentItemData().priority === "low" ? 2 : 0) : 0
                            
                            onCurrentTextChanged: {
                                if (editorModel) {
                                    editorModel.setFieldValue("priority", currentText)
                                }
                            }
                        }
                    }
                }
                
                // Description editor
                GroupBox {
                    title: "Description"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 200
                    
                    ScrollView {
                        anchors.fill: parent
                        
                        TextArea {
                            id: descriptionArea
                            text: editorModel ? editorModel.getCurrentItemData().description : ""
                            placeholderText: "Enter item description (Markdown supported)"
                            wrapMode: TextEdit.Wrap
                            selectByMouse: true
                            
                            onTextChanged: {
                                if (editorModel) {
                                    editorModel.setFieldValue("description", text)
                                }
                            }
                            
                            // Enable tab key for indentation
                            Keys.onTabPressed: {
                                insert("    ")
                            }
                        }
                    }
                }
                
                // Parent item reference
                GroupBox {
                    title: "Parent Item"
                    Layout.fillWidth: true
                    
                    RowLayout {
                        Label { text: "Parent:" }
                        TextField {
                            id: parentField
                            Layout.fillWidth: true
                            text: editorModel ? editorModel.getCurrentItemData().parent : ""
                            placeholderText: "REQ-000 (optional)"
                            readOnly: true
                        }
                        
                        Button {
                            text: "Browse..."
                            onClicked: console.log("Browse for parent item")
                        }
                    }
                }
            }
        }

        // Validation error display area
        Rectangle {
            Layout.preferredHeight: 30
            color: itemEditorPanel.validationError ? "#ffe6e6" : "#f0f0f0"
            border.color: itemEditorPanel.validationError ? "#ff4444" : "#ddd"
            visible: itemEditorPanel.validationError !== ""
            
            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                
                Label { 
                    text: "⚠"
                    color: "#ff4444"
                    font.bold: true
                }
                
                Label { 
                    id: errorLabel
                    text: itemEditorPanel.validationError || "No errors"
                    color: "#cc0000"
                    Layout.fillWidth: true
                }
                
                Button {
                    text: "OK"
                    onClicked: itemEditorPanel.validationError = ""
                    visible: itemEditorPanel.validationError !== ""
                }
            }
        }
    }

    // Properties for validation state
    property string validationError: ""
    
    // Signal emitted when item is saved
    signal itemSaved()
    
    // Signal for validation errors
    signal showValidationError(string fieldName, string message)

    // Connect validation errors from model to QML
    Connections {
        target: itemEditorPanel.editorModel
        
        function onValidation_error(fieldName, message) {
            itemEditorPanel.validationError = message
            itemEditorPanel.showValidationError(fieldName, message)
        }
        
        function onDirty_state_changed(isDirty) {
            itemEditorPanel.isDirty = isDirty
        }
    }

    // Load item from Python context
    function loadItemFromContext(itemData) {
        if (editorModel && itemData) {
            editorModel.loadItem(itemData)
            console.log("Item loaded into editor:", itemData.id)
        } else {
            console.log("Warning: No editor model or item data provided")
        }
    }

    Component.onCompleted: {
        console.log("ItemEditorPanel initialized")
    }
}
