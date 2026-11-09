pragma ComponentBehavior: Bound
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// Standalone view contract: the host can supply persisted values and listen to
// selection signals. Persistence, OS theme observation and applying a profile
// to the application belong to the eventual settings integration.
Dialog {
    id: settingsDialog
    objectName: "settingsDialog"
    title: qsTr("Settings")
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    anchors.centerIn: Overlay.overlay
    width: Math.min(468, Math.max(300, (parent ? parent.width : 440) - 32))
    height: Math.min(620, Math.max(340, (parent ? parent.height : 560) - 32))
    padding: 0

    // Mode controls light/dark behavior; a color profile only selects colors.
    // The host resolves "auto" from the OS preference and keeps it updated.
    property string themeMode: "night" // night | day | auto
    property string colorProfile: "Dark Teal"
    property int fontSize: 12
    property int density: -1
    property bool spellcheckEnabled: true
    property string spellingLanguage: "en"
    // Entries are { id: string, name: string }; the host can persist these in
    // per-user QSettings and restore them when constructing this dialog.
    property var customProfiles: []
    property var availableLanguages: [
        { code: "en", name: qsTr("English (en)") },
        { code: "de", name: qsTr("Deutsch (de)") },
        { code: "es", name: qsTr("Español (es)") },
        { code: "fr", name: qsTr("Français (fr)") },
        { code: "it", name: qsTr("Italiano (it)") },
        { code: "pt", name: qsTr("Português (pt)") }
    ]
    readonly property var profileOptions: [
        { id: "Day", name: qsTr("Day") },
        { id: "Dark Teal", name: qsTr("Dark Teal") }
    ].concat(customProfiles)

    signal themeModeSelected(string mode)
    signal colorProfileSelected(string profileId)
    signal fontSizeSelected(int size)
    signal densitySelected(int value)
    signal spellcheckSelected(bool enabled)
    signal spellingLanguageSelected(string languageCode)
    // Create a color-only copy of sourceProfileId; never copy window layout.
    signal customProfileCreated(string profileId, string name, string sourceProfileId)
    // The host removes persisted custom profiles; the local list is cleared first.
    signal resetToDefaultsRequested()

    function profileIndex() {
        for (let i = 0; i < profileOptions.length; ++i)
            if (profileOptions[i].id === colorProfile) return i
        return 0
    }

    function languageIndex() {
        for (let i = 0; i < availableLanguages.length; ++i)
            if (availableLanguages[i].code === spellingLanguage) return i
        return 0
    }

    function chooseMode(mode) {
        if (themeMode === mode) return
        themeMode = mode
        themeModeSelected(mode)
    }

    function chooseProfile(profileId) {
        if (colorProfile === profileId) return
        colorProfile = profileId
        colorProfileSelected(profileId)
    }

    function chooseFontSize(size) {
        if (fontSize === size) return
        fontSize = size
        fontSizeSelected(size)
    }

    function chooseDensity(value) {
        if (density === value) return
        density = value
        densitySelected(value)
    }

    function chooseSpellcheck(enabled) {
        if (spellcheckEnabled === enabled) return
        spellcheckEnabled = enabled
        spellcheckSelected(enabled)
    }

    function chooseLanguage(code) {
        if (spellingLanguage === code) return
        spellingLanguage = code
        spellingLanguageSelected(code)
    }

    function resetDefaults() {
        chooseMode("night")
        chooseProfile("Dark Teal")
        chooseFontSize(12)
        chooseDensity(-1)
        chooseSpellcheck(true)
        chooseLanguage("en")
        customProfiles = []
        resetToDefaultsRequested()
    }

    onOpened: closeButton.forceActiveFocus()

    background: Rectangle {
        color: "#14202b"
        radius: 12
        border.color: "#55717a"
        border.width: 1
    }

    header: Item { implicitHeight: 0 }

    contentItem: ColumnLayout {
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 20
            Layout.rightMargin: 16
            Layout.topMargin: 17
            Layout.bottomMargin: 12
            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    text: qsTr("SETTINGS  /  PREFERENCES")
                    color: "#7ddac4"
                    font.family: "DejaVu Sans Mono"
                    font.pixelSize: 13
                    font.bold: true
                }
                Label {
                    text: qsTr("Changes take effect immediately")
                    color: "#b4cbd0"
                    font.pixelSize: 11
                }
            }
            Button {
                id: closeButton
                objectName: "settingsCloseButton"
                text: qsTr("Close ✕")
                Accessible.name: qsTr("Close settings")
                onClicked: settingsDialog.close()
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#38535d" }

        ScrollView {
            id: settingsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: settingsScroll.availableWidth
                spacing: 10

                Item { Layout.preferredHeight: 4 }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    implicitHeight: appearanceContent.implicitHeight + 28
                    radius: 8
                    color: "#21333e"
                    border.color: "#38535d"

                    ColumnLayout {
                        id: appearanceContent
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 9

                        Label {
                            text: qsTr("01  APPEARANCE")
                            color: "#7ddac4"
                            font.family: "DejaVu Sans Mono"
                            font.pixelSize: 12
                            font.bold: true
                        }
                        Label { text: qsTr("Theme mode"); color: "#e8f1f2"; font.bold: true }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Repeater {
                                model: [qsTr("Night"), qsTr("Day"), qsTr("Auto")]
                                Button {
                                    id: modeButton
                                    required property string modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    text: modelData
                                    checkable: true
                                    checked: settingsDialog.themeMode === ["night", "day", "auto"][index]
                                    Accessible.name: qsTr("%1 theme mode").arg(modelData)
                                    onClicked: settingsDialog.chooseMode(["night", "day", "auto"][index])
                                    background: Rectangle {
                                        radius: 5
                                        color: modeButton.checked ? "#236a68" : "#142630"
                                        border.color: modeButton.activeFocus ? "#e8f1f2" : modeButton.checked ? "#7ddac4" : "#55717a"
                                        border.width: 1
                                    }
                                    contentItem: Text {
                                        text: modeButton.text
                                        color: "#e8f1f2"
                                        font: modeButton.font
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Auto follows your system's light or dark setting.")
                            color: "#b4cbd0"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                        Label { text: qsTr("Color profile"); color: "#e8f1f2"; font.bold: true }
                        ComboBox {
                            id: profilePicker
                            objectName: "colorProfileSelector"
                            Layout.fillWidth: true
                            model: settingsDialog.profileOptions
                            textRole: "name"
                            currentIndex: settingsDialog.profileIndex()
                            Accessible.name: qsTr("Color profile")
                            onActivated: (index) => settingsDialog.chooseProfile(settingsDialog.profileOptions[index].id)
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Button {
                                text: qsTr("New profile…")
                                Accessible.name: qsTr("Create a custom color profile")
                                onClicked: {
                                    profileNameRow.visible = !profileNameRow.visible
                                    if (profileNameRow.visible) profileName.forceActiveFocus()
                                }
                            }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout {
                            id: profileNameRow
                            Layout.fillWidth: true
                            visible: false
                            TextField {
                                id: profileName
                                Layout.fillWidth: true
                                placeholderText: qsTr("Profile name")
                                Accessible.name: qsTr("New color profile name")
                                maximumLength: 48
                                onAccepted: createProfileButton.clicked()
                            }
                            Button {
                                id: createProfileButton
                                text: qsTr("Create")
                                Accessible.name: qsTr("Create color profile")
                                enabled: profileName.text.trim().length > 0
                                onClicked: {
                                    const name = profileName.text.trim()
                                    if (!name) return
                                    const id = "custom-" + Date.now()
                                    const sourceId = settingsDialog.colorProfile
                                    settingsDialog.customProfiles = settingsDialog.customProfiles.concat([{ id: id, name: name }])
                                    settingsDialog.customProfileCreated(id, name, sourceId)
                                    settingsDialog.chooseProfile(id)
                                    profileName.text = ""
                                    profileNameRow.visible = false
                                    profilePicker.forceActiveFocus()
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    implicitHeight: readingContent.implicitHeight + 28
                    radius: 8
                    color: "#21333e"
                    border.color: "#38535d"

                    ColumnLayout {
                        id: readingContent
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 10
                        Label {
                            text: qsTr("02  READING & EDITING")
                            color: "#7ddac4"
                            font.family: "DejaVu Sans Mono"
                            font.pixelSize: 12
                            font.bold: true
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: qsTr("Font size"); color: "#e8f1f2"; font.bold: true; Layout.fillWidth: true }
                            SpinBox {
                                objectName: "fontSizeSpinBox"
                                from: 6
                                to: 20
                                value: settingsDialog.fontSize
                                editable: true
                                Accessible.name: qsTr("Font size")
                                onValueModified: settingsDialog.chooseFontSize(value)
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: qsTr("Density"); color: "#e8f1f2"; font.bold: true; Layout.fillWidth: true }
                            SpinBox {
                                objectName: "densitySpinBox"
                                from: -10
                                to: 10
                                value: settingsDialog.density
                                editable: true
                                Accessible.name: qsTr("Density")
                                onValueModified: settingsDialog.chooseDensity(value)
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.leftMargin: 12
                    Layout.rightMargin: 12
                    implicitHeight: spellingContent.implicitHeight + 28
                    radius: 8
                    color: "#21333e"
                    border.color: "#38535d"

                    ColumnLayout {
                        id: spellingContent
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 10
                        Label {
                            text: qsTr("03  SPELLING")
                            color: "#7ddac4"
                            font.family: "DejaVu Sans Mono"
                            font.pixelSize: 12
                            font.bold: true
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: qsTr("Check spelling"); color: "#e8f1f2"; font.bold: true; Layout.fillWidth: true }
                            Switch {
                                objectName: "spellcheckSwitch"
                                checked: settingsDialog.spellcheckEnabled
                                Accessible.name: qsTr("Check spelling")
                                onToggled: settingsDialog.chooseSpellcheck(checked)
                            }
                        }
                        Label { text: qsTr("Language"); color: "#e8f1f2"; font.bold: true }
                        ComboBox {
                            objectName: "spellingLanguageSelector"
                            Layout.fillWidth: true
                            enabled: settingsDialog.spellcheckEnabled
                            model: settingsDialog.availableLanguages
                            textRole: "name"
                            currentIndex: settingsDialog.languageIndex()
                            Accessible.name: qsTr("Spelling language")
                            onActivated: (index) => settingsDialog.chooseLanguage(settingsDialog.availableLanguages[index].code)
                        }
                        Label {
                            Layout.fillWidth: true
                            text: qsTr("Your language stays selected when spelling is off.")
                            color: "#b4cbd0"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }
                }
                Item { Layout.preferredHeight: 4 }
            }
        }

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#38535d" }
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            Layout.topMargin: 9
            Layout.bottomMargin: 9
            Button {
                text: qsTr("Reset defaults")
                Accessible.name: qsTr("Reset settings to built-in defaults and remove custom profiles")
                onClicked: settingsDialog.resetDefaults()
            }
            Item { Layout.fillWidth: true }
            Label {
                text: qsTr("No Apply needed")
                color: "#b4cbd0"
                font.pixelSize: 11
            }
        }
    }
}
