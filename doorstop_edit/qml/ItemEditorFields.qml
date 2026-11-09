pragma ComponentBehavior: Bound
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Standalone, controlled form. The host supplies an ordered field schema and a
// value snapshot, and owns validation, drafts, persistence and navigation.
// fields: [{key, label, kind: "text" | "multiline" | "boolean",
//           placeholder?, readOnly?, enabled?}]. Unknown kinds remain visible.
// values: {key: value}; errors: {key: message}. Keys must be unique.
ScrollView {
    id: root
    implicitWidth: 420
    implicitHeight: 480
    contentWidth: availableWidth

    property var fields: []
    property var values: ({})
    property var errors: ({})
    property bool dirty: false
    property bool pending: false
    property bool readOnly: false
    property bool canSave: false
    property bool canRevert: false

    signal fieldEdited(string key, var value)
    signal saveRequested()
    signal revertRequested()

    function hasValue(key) {
        return values !== null && values !== undefined
               && Object.prototype.hasOwnProperty.call(values, key)
    }
    function fieldValue(key) { return hasValue(key) ? values[key] : undefined }
    function displayValue(key) {
        const value = fieldValue(key)
        if (value === undefined) return qsTr("Value not supplied")
        if (value === null) return qsTr("null")
        if (typeof value === "object") return JSON.stringify(value)
        return String(value)
    }
    function errorFor(key) {
        if (!errors || !Object.prototype.hasOwnProperty.call(errors, key)) return ""
        return errors[key] === null || errors[key] === undefined ? "" : String(errors[key])
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: 12

        Label {
            Layout.fillWidth: true
            visible: root.dirty || root.pending
            text: root.pending ? qsTr("Saving…") : qsTr("Unsaved changes")
            Accessible.name: text
        }

        Repeater {
            model: root.fields || []
            delegate: ColumnLayout {
                id: row
                Layout.fillWidth: true
                spacing: 4
                required property var modelData
                required property int index
                readonly property var field: modelData || ({})
                readonly property string fieldKey: field.key === undefined || field.key === null
                                                    ? "" : String(field.key)
                readonly property string fieldLabel: field.label === undefined || field.label === null
                                                      ? (fieldKey || qsTr("Field %1").arg(index + 1)) : String(field.label)
                readonly property string kind: field.kind === undefined ? "" : String(field.kind)
                readonly property bool hasTypedValue: root.hasValue(fieldKey)
                    && ((kind === "boolean" && typeof root.fieldValue(fieldKey) === "boolean")
                        || ((kind === "text" || kind === "multiline")
                            && typeof root.fieldValue(fieldKey) === "string"))
                readonly property bool supported: fieldKey.length > 0 && hasTypedValue
                    && (kind === "text" || kind === "multiline" || kind === "boolean")
                readonly property bool canEdit: root.enabled && !root.pending && !root.readOnly
                    && field.enabled !== false && field.readOnly !== true

                Label {
                    objectName: "fieldLabel_" + row.index
                    Layout.fillWidth: true
                    text: row.fieldLabel
                    font.bold: true
                    wrapMode: Text.WordWrap
                }

                Loader {
                    id: inputLoader
                    Layout.fillWidth: true
                    Layout.preferredHeight: row.kind === "multiline" && row.supported ? 140 : implicitHeight
                    sourceComponent: !row.supported ? fallbackComponent
                                     : row.kind === "boolean" ? booleanComponent
                                     : row.kind === "multiline" ? multilineComponent : textComponent
                }

                Label {
                    objectName: "fieldError_" + row.index
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: root.errorFor(row.fieldKey)
                    color: palette.text
                    font.bold: true
                    wrapMode: Text.WordWrap
                    Accessible.name: row.fieldLabel + ": " + text
                }

                Component {
                    id: textComponent
                    TextField {
                        objectName: "fieldInput_" + row.index
                        text: root.fieldValue(row.fieldKey)
                        placeholderText: row.field.placeholder || ""
                        readOnly: !row.canEdit
                        enabled: root.enabled && row.field.enabled !== false
                        activeFocusOnTab: true
                        Accessible.name: row.fieldLabel
                        Accessible.description: root.errorFor(row.fieldKey)
                        onTextEdited: root.fieldEdited(row.fieldKey, text)
                    }
                }

                Component {
                    id: multilineComponent
                    ScrollView {
                        implicitHeight: 140
                        TextArea {
                            objectName: "fieldInput_" + row.index
                            text: root.fieldValue(row.fieldKey)
                            placeholderText: row.field.placeholder || ""
                            wrapMode: TextArea.Wrap
                            readOnly: !row.canEdit
                            enabled: root.enabled && row.field.enabled !== false
                            activeFocusOnTab: true
                            Accessible.name: row.fieldLabel
                            Accessible.description: root.errorFor(row.fieldKey)
                            onTextEdited: root.fieldEdited(row.fieldKey, text)
                        }
                    }
                }

                Component {
                    id: booleanComponent
                    CheckBox {
                        objectName: "fieldInput_" + row.index
                        checked: root.fieldValue(row.fieldKey)
                        enabled: row.canEdit
                        activeFocusOnTab: true
                        Accessible.name: row.fieldLabel
                        Accessible.description: root.errorFor(row.fieldKey)
                        onToggled: root.fieldEdited(row.fieldKey, checked)
                    }
                }

                Component {
                    id: fallbackComponent
                    Label {
                        objectName: "fieldFallback_" + row.index
                        width: inputLoader.width
                        text: root.displayValue(row.fieldKey) + qsTr(" (not editable)")
                        wrapMode: Text.WrapAnywhere
                        Accessible.name: row.fieldLabel + ": " + text
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button {
                objectName: "revertButton"
                text: qsTr("Revert")
                enabled: root.enabled && root.canRevert && !root.pending && !root.readOnly
                Accessible.name: qsTr("Revert edits")
                onClicked: root.revertRequested()
            }
            Button {
                objectName: "saveButton"
                text: root.pending ? qsTr("Saving…") : qsTr("Save")
                enabled: root.enabled && root.canSave && !root.pending && !root.readOnly
                Accessible.name: qsTr("Save edits")
                onClicked: root.saveRequested()
            }
        }
    }
}
