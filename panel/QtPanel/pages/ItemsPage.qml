pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../DesignSystem/FriendlyCopy.js" as FriendlyCopy
import "../DesignSystem/Status.js" as Status
import "../components" as Ui

// Items & Money (FINAL-VISUAL-SPEC.md 4.3, IA-SPEC.md 2.3).
//
// One column (window under 1880 px): Money, Add items, More items. The Add
// items card ends at the bottom of the window: its list takes the height
// that is left (never fewer than 5 rows), so you search, pick and press
// Add Item without scrolling the page. Under 840 px of window height the
// Money card folds its controls into one 40 px row, and the four quick
// amounts move into the menu beside the Amount box.
//
// Maximized (window.wideItems, 1880 px and wider): two 600 px columns with
// a 16 px gap. Add items runs the full height on the left; Money (full
// form) sits above More items on the right. Columns are top-aligned and
// cards are never stretched to match.
//
// Player copy rules: statuses are Ready / Waiting for game / Adding /
// Added (plus Off, Needs update and Couldn't start safely); no internal
// words, and no raw item identifiers.
Ui.PageScroll {
    id: root
    property var appBackend
    property var windowRoot
    pageId: "items"

    readonly property bool hasSelection: root.appBackend.selectedAlias.length > 0
    readonly property bool routeReady: root.appBackend.liveAddReady && !root.appBackend.liveAddBusy
    // The chosen item can be added right now: the game mod labels it Ready.
    readonly property bool canAdd: routeReady && hasSelection && root.appBackend.selectedAddable
    readonly property bool canAddMoney: root.appBackend.moneyLiveAddReady && !root.appBackend.liveAddBusy
    // A large money amount waits for its second, explicit "Yes, add".
    readonly property bool confirmingMoney: root.appBackend.moneyConfirmAmount > 0
    readonly property bool searching: searchField.text.trim().length > 0

    // ── Layout ───────────────────────────────────────────────────────────
    readonly property bool wide: root.windowRoot ? root.windowRoot.wideItems === true : false
    readonly property real windowHeight: root.windowRoot && root.windowRoot.height > 0
                                         ? root.windowRoot.height : root.height
    // Money's one-row form keeps 5 list rows and Add Item on screen at
    // 1040 x 720 (FINAL-VISUAL-SPEC.md 12.4).
    readonly property bool compactMoney: !root.wide && root.windowHeight < 840
    readonly property int gapSize: root.tokens ? root.tokens.gap : 16
    readonly property int cardPad: root.tokens ? root.tokens.cardPad : 16
    readonly property int controlGap: root.tokens ? root.tokens.spaceXs : 8
    readonly property int bodyGap: root.tokens ? root.tokens.spaceSm : 12
    readonly property int controlHeight: root.tokens ? root.tokens.fieldHeight : 40
    // SbCard's header: the 24 px title row, 4 px, then its one 20 px line.
    readonly property int cardHeader: 24 + (root.tokens ? root.tokens.spaceXxs : 4) + 20
    // The add bar under the list: name + chip (24), one line (20), 8 px,
    // then Quantity and Add Item (40), after 12 px under the list.
    readonly property int addBarHeight: 104
    readonly property int listRowHeight: root.tokens ? root.tokens.catalogRowHeight : 44
    readonly property int listMinRows: 5
    readonly property bool itemResultShown: root.hasSelection && root.appBackend.itemLastResult.length > 0
    // Everything in the Add items card except the list itself.
    readonly property real addCardChrome: root.cardPad * 2 + root.cardHeader + root.bodyGap
                                          + root.controlHeight + root.bodyGap + root.addBarHeight
                                          + (root.itemResultShown ? root.bodyGap + itemResult.implicitHeight : 0)
    // The list fills what is left of the window in whole rows, so its
    // bottom edge never cuts a row through its text, and never shows fewer
    // than 5 rows. What is left under the last whole row (listSlack, less
    // than a row) stays at the foot of the card, so the card still ends at
    // the window's bottom edge.
    readonly property real listRoom: root.height - root.addCardChrome
                                     - (root.wide ? 0 : moneyCard.height + root.gapSize)
    readonly property int listHeight: root.listRowHeight
                                      * Math.max(root.listMinRows, Math.floor(root.listRoom / root.listRowHeight))
    readonly property int listSlack: Math.max(0, 2 * Math.floor((root.listRoom - root.listHeight) / 2))

    // ── Status words ─────────────────────────────────────────────────────
    // Why items can't be added right now (the old Status card's line).
    readonly property string routeLine: !root.appBackend.liveAddInstalled
                                        ? "The Items & Money game mod is not installed."
                                        : root.appBackend.liveAddStatus
    // The Money chip never goes blank.
    readonly property string moneyChip: root.appBackend.moneyAdding ? "Adding"
                                        : root.canAddMoney ? "Ready"
                                        : !root.appBackend.liveAddReady ? root.appBackend.itemsStatusLabel
                                        : ({checking: "Checking", at_limit: "At limit", needs_dlc: "Needs DLC",
                                             not_available: "Not available"})[root.appBackend.moneyStatusState] || "Not available"
    readonly property string moneyChipKind: root.appBackend.moneyAdding ? "warn"
                                            : root.canAddMoney ? "ok"
                                            : !root.appBackend.liveAddReady ? Status.kindForState(root.appBackend.itemsStatusState)
                                            : root.appBackend.moneyStatusState === "not_available" ? "off" : "warn"
    // The add bar's second line: why the chosen item can't be added (amber),
    // or its notes and description.
    readonly property bool addLineWarns: root.hasSelection
                                         && (root.appBackend.selectedReason.length > 0 || !root.appBackend.liveAddReady)
    // With nothing chosen, a hint fills the line; the Money card and this
    // card's chip already say when the game mod can't add anything.
    readonly property string addLine: {
        if (!root.hasSelection)
            return "Search by name, or pick a category."
        if (root.appBackend.selectedReason.length > 0)
            return root.appBackend.selectedReason
        if (!root.appBackend.liveAddReady)
            return root.routeLine
        return [root.appBackend.selectedNote, root.appBackend.selectedDescription]
            .filter(part => part.length > 0).join(" ")
    }

    // A new amount replaces the one waiting for confirmation.
    function dropMoneyConfirm() {
        if (root.confirmingMoney)
            root.appBackend.cancelLiveAddMoney()
    }
    function pickPreset(amount) {
        moneyBox.value = amount
        root.dropMoneyConfirm()
    }
    // Search + category the catalog was last positioned for.
    property string appliedFilterKey: ""

    function groupedNumber(value) {
        return Number(value).toLocaleString(Qt.locale("en_US"), "f", 0)
    }

    // The currency picker (Other currencies on): Gold first, then the rest.
    // It follows the currency the backend has chosen.
    component CurrencyPicker: Ui.SbComboBox {
        id: picker
        property var backend: null
        textRole: "name"
        valueRole: "alias"
        model: picker.backend ? picker.backend.moneyCurrencies : []
        Component.onCompleted: picker.follow()
        onModelChanged: picker.follow()
        onActivated: picker.backend.setMoneyCurrency(picker.currentValue)
        function follow(): void {
            if (!picker.backend)
                return
            const index = picker.indexOfValue(picker.backend.moneyAlias)
            if (index !== picker.currentIndex)
                picker.currentIndex = Math.max(0, index)
        }
        Connections {
            target: picker.backend
            function onLiveAddChanged() { picker.follow() }
        }
    }

    Item {
        id: layoutBox
        objectName: "itemsLayout"
        Layout.fillWidth: true
        Layout.preferredHeight: implicitHeight
        readonly property real columnWidth: root.wide ? Math.floor((width - root.gapSize) / 2) : width
        readonly property real rightX: root.wide ? columnWidth + root.gapSize : 0
        readonly property real rightWidth: root.wide ? width - rightX : width
        implicitHeight: root.wide ? Math.max(addCard.y + addCard.height, moreCard.y + moreCard.height)
                                  : moreCard.y + moreCard.height

        // ── Money ────────────────────────────────────────────────────────
        Ui.SbCard {
            id: moneyCard
            objectName: "itemsMoneyCard"
            x: layoutBox.rightX
            y: 0
            width: layoutBox.rightWidth
            height: implicitHeight
            appBackend: root.appBackend
            tokens: root.tokens
            icon: "money"
            title: "Money"
            neonTag: "MONEY"
            status: root.moneyChip
            statusKind: root.moneyChipKind
            accentActive: root.canAddMoney
            // One line: how much you have and the most one add sends, or why
            // money can't be added right now.
            subtitle: root.appBackend.moneyLiveAddStatus
            helpTip: "Money is added through the game's own inventory, like items. "
                     + "Amounts of " + root.groupedNumber(100000) + " or more ask once more before "
                     + "anything is sent."

            // Quick amounts (full form); the Amount box takes any amount up
            // to the limit.
            RowLayout {
                objectName: "itemsMoneyPresets"
                Layout.fillWidth: true
                visible: !root.compactMoney
                spacing: root.controlGap
                Repeater {
                    model: root.appBackend.moneyPresets
                    delegate: Ui.SbButton {
                        required property var modelData
                        objectName: "itemsMoneyPreset"
                        tokens: root.tokens
                        // Four equal buttons.
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.minimumWidth: 0
                        text: root.groupedNumber(modelData)
                        // The amount in the box: accent outline (the button's
                        // open look; SbButton has no separate "chosen" state).
                        menuOpen: moneyBox.value === modelData
                        onClicked: root.pickPreset(modelData)
                    }
                }
            }

            RowLayout {
                id: amountRow
                objectName: "itemsMoneyAmountRow"
                Layout.fillWidth: true
                Layout.preferredHeight: root.controlHeight
                // The compact form swaps this row for the question.
                visible: !(root.compactMoney && root.confirmingMoney)
                spacing: root.controlGap
                // Down to the 720 px window minimum the compact row still fits
                // on one line: below 620 px of card content the "Amount" word
                // goes (the card line names the currency) and the picker
                // narrows. Read from the card, not this row, whose width
                // follows its own contents when they overflow.
                readonly property bool narrow: moneyCard.width - 2 * root.cardPad < 620

                // Compact form: Other currencies leads the row.
                Ui.SbSwitch {
                    id: compactCurrencies
                    objectName: "itemsMoneyCompactCurrencies"
                    visible: root.compactMoney
                    tokens: root.tokens
                    checked: root.appBackend.moneyOtherCurrencies
                    onToggled: root.appBackend.setItemsOptIn("currencies", checked)
                }
                Text {
                    objectName: "itemsMoneyCompactCurrenciesLabel"
                    visible: root.compactMoney && !root.appBackend.moneyOtherCurrencies
                    Layout.leftMargin: 4
                    text: "Other currencies"
                    textFormat: Text.PlainText
                    color: root.tokens.textPrimary
                    font.pixelSize: root.tokens.fontBody
                    font.family: root.tokens.typeFamily
                    font.hintingPreference: root.tokens.textHinting
                    HoverHandler {
                        id: compactCurrenciesHover
                        cursorShape: Qt.PointingHandCursor
                    }
                    TapHandler { onTapped: compactCurrencies.click() }
                    Ui.SbToolTip {
                        tokens: root.tokens
                        visible: compactCurrenciesHover.hovered
                        text: "Adds Vitcoin, Fishing Score, Micro Drive, Micro Motor and Micro Coil to the Currency list."
                    }
                }
                // With Other currencies on, the picker takes the label's place
                // so the form stays one row.
                CurrencyPicker {
                    objectName: "itemsCompactCurrencyBox"
                    visible: root.compactMoney && root.appBackend.moneyOtherCurrencies
                    Layout.leftMargin: 4
                    Layout.preferredWidth: amountRow.narrow ? 136 : 160
                    tokens: root.tokens
                    backend: root.appBackend
                }
                Item {
                    visible: root.compactMoney
                    Layout.fillWidth: true
                }

                Text {
                    // The picker's currency names the box in the compact row.
                    visible: !(root.compactMoney && (root.appBackend.moneyOtherCurrencies || amountRow.narrow))
                    Layout.rightMargin: 4
                    text: "Amount"
                    textFormat: Text.PlainText
                    color: root.tokens.textSecondary
                    font.pixelSize: root.tokens.fontBody
                    font.family: root.tokens.typeFamily
                    font.hintingPreference: root.tokens.textHinting
                }
                Ui.SbSpinBox {
                    id: moneyBox
                    objectName: "itemsMoneyBox"
                    tokens: root.tokens
                    Layout.fillWidth: !root.compactMoney
                    Layout.preferredWidth: amountRow.narrow ? 148 : root.tokens.fieldWidth
                    Layout.minimumWidth: 148
                    from: 1
                    // The most one add may send now (the room left once the game
                    // mod reports it), so the amount shown is the amount sent.
                    to: Math.max(1, root.canAddMoney && root.appBackend.moneyMaxAdd > 0
                                    ? root.appBackend.moneyMaxAdd : root.appBackend.moneyTierMax)
                    value: 1000
                    stepSize: root.appBackend.moneyTierMax >= 100000 ? 1000 : 10
                    editable: true
                    textFromValue: function(value, locale) { return root.groupedNumber(value) }
                    valueFromText: function(text, locale) {
                        const digits = String(text).replace(/[^0-9]/g, "")
                        return digits.length > 0 ? Math.min(moneyBox.to, Math.max(moneyBox.from, parseInt(digits, 10))) : moneyBox.from
                    }
                    onValueModified: root.dropMoneyConfirm()
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                }
                // Compact form: the quick amounts, in a menu beside the box.
                Ui.SbButton {
                    id: presetMenuButton
                    objectName: "itemsMoneyPresetMenuButton"
                    visible: root.compactMoney
                    tokens: root.tokens
                    Layout.preferredWidth: root.controlHeight
                    Layout.preferredHeight: root.controlHeight
                    iconName: "chevronDown"
                    menuOpen: presetMenu.opened
                    onClicked: presetMenu.openUnder(presetMenuButton)
                    Ui.SbToolTip {
                        tokens: root.tokens
                        visible: presetMenuButton.hovered && !presetMenu.opened
                        text: "Quick amounts"
                    }

                    Ui.SbMenu {
                        id: presetMenu
                        objectName: "itemsMoneyPresetMenu"
                        tokens: root.tokens
                        // The check follows the amount in the box.
                        onAboutToShow: {
                            const amounts = root.appBackend.moneyPresets
                            for (let i = 0; i < presetMenu.count; ++i) {
                                const entry = presetMenu.itemAt(i) as Ui.SbMenuItem
                                if (entry)
                                    entry.checked = moneyBox.value === amounts[i]
                            }
                        }
                        Instantiator {
                            model: root.appBackend.moneyPresets
                            delegate: Ui.SbMenuItem {
                                required property var modelData
                                objectName: "itemsMoneyPresetItem"
                                tokens: root.tokens
                                text: root.groupedNumber(modelData)
                                checkable: true
                                onTriggered: root.pickPreset(modelData)
                            }
                            onObjectAdded: (index, object) => presetMenu.insertItem(index, object)
                            onObjectRemoved: (index, object) => presetMenu.removeItem(object)
                        }
                    }
                }
                Ui.SbButton {
                    objectName: "itemsMoneyAddButton"
                    tokens: root.tokens
                    Layout.preferredWidth: amountRow.narrow ? 128 : root.tokens.primaryActionWidth
                    text: root.appBackend.moneyAdding ? "Adding…" : "Add " + root.appBackend.moneyName
                    // While the question is open, its "Yes, add" is the one
                    // primary button.
                    variant: root.confirmingMoney ? "secondary" : "primary"
                    enabled: root.canAddMoney && !root.confirmingMoney
                    onClicked: root.appBackend.requestLiveAddMoney(moneyBox.value)
                }
            }

            // A large amount is never sent on one click: the panel asks once
            // more, with the exact amount, and sends only on "Yes, add".
            RowLayout {
                objectName: "itemsMoneyConfirm"
                Layout.fillWidth: true
                Layout.preferredHeight: root.controlHeight
                visible: root.confirmingMoney
                spacing: root.controlGap

                Text {
                    objectName: "itemsMoneyConfirmText"
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "Add " + root.groupedNumber(root.appBackend.moneyConfirmAmount) + " " + root.appBackend.moneyName + "?"
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: root.tokens.statusWarnInk
                    font.pixelSize: root.tokens.fontBody
                    font.family: root.tokens.typeSemibold
                    font.weight: Font.DemiBold
                    font.hintingPreference: root.tokens.textHinting
                }
                Ui.SbButton {
                    objectName: "itemsMoneyConfirmCancel"
                    tokens: root.tokens
                    text: "Cancel"
                    onClicked: root.appBackend.cancelLiveAddMoney()
                }
                Ui.SbButton {
                    objectName: "itemsMoneyConfirmAdd"
                    tokens: root.tokens
                    Layout.preferredWidth: root.tokens.primaryActionWidth
                    text: "Yes, add"
                    variant: "primary"
                    enabled: root.canAddMoney
                    onClicked: root.appBackend.confirmLiveAddMoney()
                }
            }

            // The last money add's line ("Adding 1,000 Gold...", "Added 1,000
            // Gold." or why nothing was added), on the card that sent it.
            Text {
                objectName: "itemsMoneyResult"
                Layout.fillWidth: true
                visible: text.length > 0
                text: root.appBackend.moneyLastResult
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                lineHeightMode: Text.FixedHeight
                lineHeight: 20
                color: root.tokens.textSecondary
                font.pixelSize: root.tokens.fontCaption
                font.family: root.tokens.typeFamily
                font.hintingPreference: root.tokens.textHinting
            }

            // Other currencies are opt-in; with them on, pick which one to add.
            // (The compact form has its switch and picker in the row above.)
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                visible: !root.compactMoney

                Ui.SettingsField {
                    objectName: "itemsOptIn_currencies"
                    tokens: root.tokens
                    label: "Other currencies"
                    hint: "Vitcoin, Fishing Score, Micro Drive, Micro Motor and Micro Coil."
                    hasControl: true
                    compactControl: true
                    showSeparator: false
                    Ui.SbSwitch {
                        objectName: "itemsOptInSwitch_currencies"
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        tokens: root.tokens
                        checked: root.appBackend.moneyOtherCurrencies
                        onToggled: root.appBackend.setItemsOptIn("currencies", checked)
                    }
                }

                Ui.SettingsField {
                    objectName: "itemsCurrencyRow"
                    visible: root.appBackend.moneyOtherCurrencies
                    tokens: root.tokens
                    subRow: true
                    label: "Currency"
                    hasControl: true
                    showSeparator: false
                    CurrencyPicker {
                        objectName: "itemsCurrencyBox"
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        tokens: root.tokens
                        backend: root.appBackend
                    }
                }
            }
        }

        // ── Add items (search, pick, add) ────────────────────────────────
        Ui.SbCard {
            id: addCard
            objectName: "itemsAddCard"
            x: 0
            y: root.wide ? 0 : moneyCard.height + root.gapSize
            width: layoutBox.columnWidth
            // Its content is top-aligned; the room under the list's last
            // whole row (listSlack) stays at the card's foot.
            height: implicitHeight + root.listSlack
            appBackend: root.appBackend
            tokens: root.tokens
            icon: "items"
            title: "Add items"
            neonTag: "ITEMS"
            // Whether items can be added right now (the old Status card).
            status: root.appBackend.itemsStatusLabel
            statusKind: root.appBackend.liveAddReady ? "ok" : Status.kindForState(root.appBackend.itemsStatusState)
            accentActive: root.appBackend.liveAddReady
            // "525 items", "12 of 525 items" while a search or category narrows
            // it, plus how many more a search found that can't be added.
            subtitle: (root.appBackend.itemCount === root.appBackend.catalogCount
                       ? root.groupedNumber(root.appBackend.catalogCount) + " items"
                       : root.groupedNumber(root.appBackend.itemCount) + " of "
                         + root.groupedNumber(root.appBackend.catalogCount) + " items")
                      + (root.appBackend.itemSearchOnlyCount > 0
                         ? " · " + root.appBackend.itemSearchOnlyCount + " more can't be added" : "")
            helpTip: root.routeLine + "\n\n" + FriendlyCopy.itemsIntroSummary() + " " + FriendlyCopy.itemsIntroDetail()
                     + "\n\nSeparate from Instant Boss Restart, Retry Point, God Mode and Movement."

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: root.controlHeight
                spacing: root.controlGap

                // The shared field: its hint hides while text is present instead
                // of floating up onto the border, where it was clipped.
                Ui.SbTextField {
                    id: searchField
                    objectName: "itemsSearchField"
                    tokens: root.tokens
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    iconName: "search"
                    hint: "Search items"
                    hintObjectName: "itemsSearchPlaceholder"
                    clearable: true
                    clearObjectName: "itemsSearchClear"
                    onTextChanged: root.appBackend.setItemFilter(text, categoryBox.currentText)
                }

                Ui.SbComboBox {
                    id: categoryBox
                    objectName: "itemsCategoryBox"
                    tokens: root.tokens
                    Layout.preferredWidth: root.tokens.fieldWidth
                    // A catalog reload can add or drop categories, and a ComboBox
                    // jumps back to its first entry ("All") whenever its model
                    // changes - the player's category was silently dropped. The
                    // list is handed over here instead, keeping the choice by name.
                    readonly property var categoryNames: root.appBackend.categories
                    onCategoryNamesChanged: categoryBox.adoptCategories()
                    Component.onCompleted: categoryBox.adoptCategories()
                    function adoptCategories(): void {
                        const kept = categoryBox.currentText
                        categoryBox.model = categoryBox.categoryNames
                        const index = kept.length > 0 ? categoryBox.find(kept) : 0
                        categoryBox.currentIndex = index >= 0 ? index : 0
                    }
                    onCurrentTextChanged: root.appBackend.setItemFilter(searchField.text, currentText)
                }
            }

            // The list and, directly under it, the add bar: one block.
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Ui.ItemCatalogList {
                    id: catalog
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.listHeight
                    tokens: root.tokens
                    model: root.appBackend.itemsModel
                    categories: root.appBackend.categories
                    selectedAlias: root.appBackend.selectedAlias
                    filtered: root.searching || categoryBox.currentIndex > 0
                    firstSearchOnlyIndex: root.appBackend.itemSearchOnlyCount > 0 ? root.appBackend.itemCount : -1
                    onItemSelected: (alias, name) => root.appBackend.selectItem(alias, name)
                    onClearFilterRequested: {
                        searchField.clear()
                        categoryBox.currentIndex = 0
                    }
                }

                // The add bar: the chosen item and its chip; one line (why it
                // can't be added, or what it is); Quantity and Add Item.
                Item {
                    id: addBar
                    objectName: "itemsAddBar"
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.addBarHeight
                    implicitHeight: root.addBarHeight

                    RowLayout {
                        x: 0
                        y: root.bodyGap
                        width: parent.width
                        height: 24
                        spacing: root.bodyGap

                        Text {
                            objectName: "itemsSelectedName"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.alignment: Qt.AlignVCenter
                            text: root.hasSelection ? root.appBackend.selectedName : "Choose an item above."
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: root.hasSelection ? root.tokens.textPrimary : root.tokens.textMuted
                            font.pixelSize: root.tokens.fontBody
                            font.family: root.hasSelection ? root.tokens.typeSemibold : root.tokens.typeFamily
                            font.weight: root.hasSelection ? Font.DemiBold : Font.Normal
                            font.hintingPreference: root.tokens.textHinting
                        }
                        // The chosen item's chip, the same one its row shows.
                        Ui.StatusChip {
                            objectName: "itemsSelectedChip"
                            Layout.alignment: Qt.AlignVCenter | Qt.AlignRight
                            visible: root.hasSelection && text.length > 0
                            tokens: root.tokens
                            text: root.appBackend.selectedChipText
                            kind: root.appBackend.selectedChipKind
                        }
                    }

                    Text {
                        id: addLineText
                        objectName: "itemsSelectedDetail"
                        x: 0
                        y: root.bodyGap + 24
                        width: parent.width
                        height: 20
                        verticalAlignment: Text.AlignVCenter
                        text: root.addLine
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        color: root.addLineWarns ? root.tokens.statusWarnInk
                               : root.hasSelection ? root.tokens.textSecondary : root.tokens.textMuted
                        font.pixelSize: root.tokens.fontLabel
                        font.family: root.tokens.typeFamily
                        font.hintingPreference: root.tokens.textHinting
                        HoverHandler { id: addLineHover }
                        Ui.SbToolTip {
                            tokens: root.tokens
                            visible: addLineHover.hovered && addLineText.truncated
                            text: root.addLine
                        }
                    }

                    RowLayout {
                        x: 0
                        y: root.addBarHeight - root.controlHeight
                        width: parent.width
                        height: root.controlHeight
                        spacing: root.controlGap

                        Text {
                            Layout.rightMargin: 4
                            text: "Quantity"
                            textFormat: Text.PlainText
                            color: quantityBox.enabled ? root.tokens.textSecondary : root.tokens.textDisabled
                            font.pixelSize: root.tokens.fontBody
                            font.family: root.tokens.typeFamily
                            font.hintingPreference: root.tokens.textHinting
                        }
                        Ui.SbSpinBox {
                            id: quantityBox
                            objectName: "itemsQuantityBox"
                            tokens: root.tokens
                            from: 1
                            // The most one add may ask for now: 99 for a stack, the room
                            // left when the game mod reports it, 1 for a one-of-a-kind item.
                            to: Math.max(1, root.appBackend.selectedMaxQty > 0 ? root.appBackend.selectedMaxQty : 99)
                            value: root.appBackend.qty
                            editable: true
                            // Only a chosen item that can take more than one: not
                            // with nothing chosen, not for a one-of-a-kind item,
                            // nor for one that can't be added now (Owned, At
                            // limit, Not available: its limit is 0).
                            enabled: root.hasSelection && root.appBackend.selectedMaxQty > 1
                            onValueModified: root.appBackend.setQty(value)
                            // Pointing hand on the -/+ buttons; the number field keeps its
                            // text cursor because its own input sits above this handler.
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                        }
                        Item { Layout.fillWidth: true }
                        Ui.SbButton {
                            objectName: "itemsAddButton"
                            tokens: root.tokens
                            Layout.preferredWidth: root.tokens.primaryActionWidth
                            text: root.appBackend.liveAddBusy ? "Adding…" : "Add Item"
                            variant: "primary"
                            enabled: root.canAdd
                            onClicked: root.appBackend.requestLiveAdd()
                        }
                    }
                }
            }

            // The last item add's line. A money add reports on the Money card.
            Text {
                id: itemResult
                objectName: "itemsItemResult"
                Layout.fillWidth: true
                visible: root.itemResultShown
                text: root.appBackend.itemLastResult
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                lineHeightMode: Text.FixedHeight
                lineHeight: 20
                color: root.tokens.textSecondary
                font.pixelSize: root.tokens.fontCaption
                font.family: root.tokens.typeFamily
                font.hintingPreference: root.tokens.textHinting
            }

            // Every new search or category starts at its first result. The key is
            // compared so a catalog reload with the same filter keeps its place.
            Connections {
                target: root.appBackend
                function onItemsChanged() {
                    // Same normalisation as the filter: case and extra spaces
                    // do not make a new search.
                    const words = searchField.text.toLowerCase().split(/\s+/).filter(word => word.length > 0)
                    const key = words.join(" ") + "\n" + categoryBox.currentText
                    if (key !== root.appliedFilterKey) {
                        root.appliedFilterKey = key
                        catalog.showFirstItem()
                    }
                }
            }
        }

        // ── More items ───────────────────────────────────────────────────
        Ui.SbCard {
            id: moreCard
            objectName: "itemsMoreCard"
            x: layoutBox.rightX
            y: root.wide ? moneyCard.height + root.gapSize : addCard.y + addCard.height + root.gapSize
            width: layoutBox.rightWidth
            height: implicitHeight
            appBackend: root.appBackend
            tokens: root.tokens
            icon: "folder"
            title: "More items"
            neonTag: "MORE"
            subtitle: "Optional groups for the list. Each stays off until you turn it on."
            // The rows carry their own dividers.
            bodySpacing: 0

            Repeater {
                id: optInRows
                // Other currencies lives on the Money card.
                model: root.appBackend.itemsOptIns.filter(entry => entry.key !== "currencies")
                delegate: Ui.SettingsField {
                    id: optIn
                    required property var modelData
                    required property int index
                    objectName: "itemsOptIn_" + optIn.modelData.key
                    tokens: root.tokens
                    label: optIn.modelData.name
                    // The count leads, so a hint cut short at 600 px still
                    // says how many items the group adds (the full words are
                    // in the row's tooltip). A no-break space keeps "5 items."
                    // together.
                    hint: optIn.modelData.count + " items. " + optIn.modelData.hint
                    hasControl: true
                    compactControl: true
                    showSeparator: optIn.index < optInRows.count - 1
                    Ui.SbSwitch {
                        objectName: "itemsOptInSwitch_" + optIn.modelData.key
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        tokens: root.tokens
                        checked: optIn.modelData.on
                        onToggled: root.appBackend.setItemsOptIn(optIn.modelData.key, checked)
                    }
                }
            }
        }
    }
}
