"""Interactive, import-local policies for booking conflicts and warnings."""

import re
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout)


DISPLAY_FIELDS = (("date", "Datum"), ("account", "Konto"),
    ("security", "Wertpapier / ISIN"), ("amount", "Betrag"),
    ("fees", "Gebühren"), ("taxes", "Steuer"))
IDENTITY_IGNORED_FIELDS = {
    "source", "import_id", "id", "depot", "edited", "classification_source"}
SAFE_TEXT_WARNING_CODES = (
    (re.compile(r"^Aus dem comdirect-Zwischenspeicher", re.I), "CACHE_FRESHNESS"),
    (re.compile(r"^Separate (?:Dividenden-)?Steuermitteilung", re.I), "SEPARATE_TAX_NOTICE"),
    (re.compile(r"^(?:Zeitraum|Angefordert):", re.I), "HISTORY_RANGE_INFO"),
    (re.compile(r"^Geliefert:", re.I), "HISTORY_DELIVERY_INFO"),
    (re.compile(r"^Keine neuen gebuchten Umsätze", re.I), "NO_NEW_BOOKINGS"),
)
UNSAFE_CODE_PARTS = (
    "ERROR", "INVALID", "NONFINITE", "INTEGRITY", "IDENTITY", "CONFLICT",
    "REQUIRED", "DATABASE", "VALIDATION", "TAX_ID", "ACCOUNT_MISSING",
)


def _value(record, key):
    value = record.get(key, "")
    return "" if value is None else str(value)


def conflict_kind(conflict):
    """Group only structurally equivalent conflicts inside one import run."""
    changed = tuple(key for key, _ in DISPLAY_FIELDS
                    if _value(conflict["old"], key) != _value(conflict["new"], key))
    return bool(conflict.get("id_match")), conflict["new"].get("kind", ""), changed


def identical_conflict(conflict):
    """Recognise an unchanged booking despite storage-only metadata."""
    old, new = conflict["old"], conflict["new"]
    keys = (set(old) | set(new)) - IDENTITY_IGNORED_FIELDS
    return all(_value(old, key) == _value(new, key) for key in keys)


@dataclass(frozen=True)
class WarningNotice:
    message: str
    key: str
    plugin: str
    code: str
    category: str
    persistable: bool


def _plugin_key(batch):
    raw = getattr(batch, "plugin_id", "") or ""
    if raw:
        raw = raw.removeprefix("user.")
    else:
        evidence = " ".join((getattr(batch, "source_sheet", "") or "",
                             getattr(batch, "pdf_text", "") or ""))
        banks = [bank for bank in ("comdirect", "ing", "baader", "renault", "deka")
                 if re.search(r"\b" + bank + r"\b", evidence, re.I)]
        raw = banks[0] if len(banks) == 1 else "generic"
    return re.sub(r"[^a-z0-9_.-]+", "-", raw.casefold()).strip("-") or "generic"


def warning_notice(batch, message):
    """Build a stable, privacy-safe warning identity from source metadata."""
    plugin = _plugin_key(batch)
    code = str(getattr(message, "code", "") or "").upper()
    severity = str(getattr(message, "severity", "warning") or "warning").casefold()
    if not code:
        code = next((candidate for pattern, candidate in SAFE_TEXT_WARNING_CODES
                     if pattern.search(str(message))), "")
    persistable = bool(code and severity != "error"
                       and not any(part in code for part in UNSAFE_CODE_PARTS))
    key = f"{plugin}:{code}" if code else ""
    return WarningNotice(str(message), key, plugin, code,
                         code.replace("_", " ").title() if code else "Nicht klassifiziert",
                         persistable)


def warning_kind(message):
    """Compatibility helper for callers that only have a string."""
    if isinstance(message, WarningNotice):
        return message.key or message.category
    head = str(message).split(":", 1)[0].strip()
    return head or str(message).strip()


def persistent_warning_rows(settings):
    rules = settings.get("ignored_import_warnings", {}) if settings else {}
    return [{"key": key, **value} for key, value in sorted(rules.items())]


def remove_persistent_warning(settings, key):
    rules = dict(settings.get("ignored_import_warnings", {}))
    removed = rules.pop(key, None) is not None
    settings["ignored_import_warnings"] = rules
    return removed


def reset_persistent_warnings(settings):
    count = len(settings.get("ignored_import_warnings", {}))
    settings["ignored_import_warnings"] = {}
    return count


@dataclass
class ImportDecisionPolicy:
    """Rules exist in memory for one ImportWizard only and are never global."""
    conflict_rules: dict = field(default_factory=dict)
    warning_rules: dict = field(default_factory=dict)
    ignored_warning_count: int = 0

    def summary(self):
        return (f"Aktuelle Regeln: {len(self.conflict_rules)} Konfliktregel(n), "
                f"{len(self.warning_rules)} Warnungsregel(n), "
                f"{self.ignored_warning_count} Warnungsanzeige(n) ignoriert. "
                "Die Regeln gelten nur für diesen Importvorgang.")


class BookingConflictDialog(QDialog):
    """Compare one existing booking with its incoming replacement candidate."""
    def __init__(self, conflict, current, total, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Eintrag schon vorhanden")
        self.setMinimumWidth(820)
        self.action = None
        layout = QVBoxLayout(self)
        title = QLabel(f"Konflikt {current} von {total}")
        title.setStyleSheet("font-size: 16px; font-weight: 600")
        layout.addWidget(title)
        layout.addWidget(QLabel("Vorhandene Buchung revisionssicher ersetzen oder neue Buchung überspringen."))
        table = QTableWidget(len(DISPLAY_FIELDS) + 1, 3)
        table.setHorizontalHeaderLabels(["Feld", "Vorhandene Buchung", "Neue Buchung"])
        for row, (key, label) in enumerate((*DISPLAY_FIELDS, ("source", "Dokumentquelle"))):
            old_value, new_value = _value(conflict["old"], key), _value(conflict["new"], key)
            for column, text in enumerate((label, old_value, new_value)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, column, item)
            if old_value != new_value:
                for column in (1, 2):
                    table.item(row, column).setBackground(QColor("#fff0bd"))
                    table.item(row, column).setForeground(QColor("#222222"))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        self.scope = QComboBox()
        self.scope.addItem("Nur diesen Eintrag bearbeiten", "once")
        self.scope.addItem("Alle gleichartigen Konflikte genauso behandeln", "all")
        self.scope.addItem("Bei jedem Konflikt nachfragen", "ask")
        layout.addWidget(self.scope)
        buttons = QDialogButtonBox()
        replace = buttons.addButton("&Alte überschreiben", QDialogButtonBox.ButtonRole.AcceptRole)
        keep = buttons.addButton("Alte &behalten", QDialogButtonBox.ButtonRole.DestructiveRole)
        cancel = buttons.addButton("&Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        replace.setToolTip("Neue Buchung übernehmen; alte Version revisionssicher erhalten")
        keep.setToolTip("Vorhandene Buchung unverändert lassen; neue Buchung überspringen")
        replace.clicked.connect(lambda: self.finish("replace"))
        keep.clicked.connect(lambda: self.finish("skip"))
        cancel.clicked.connect(self.reject)
        replace.setDefault(True)
        layout.addWidget(buttons)

    def finish(self, action):
        self.action = action
        self.accept()


class WarningDecisionDialog(QDialog):
    """Warning visibility decision; never controls whether a booking is skipped."""
    def __init__(self, notice, current, total, parent=None):
        super().__init__(parent)
        if not isinstance(notice, WarningNotice):
            notice = WarningNotice(str(notice), "", "generic", "", "Nicht klassifiziert", False)
        self.setWindowTitle("Importhinweis")
        self.action = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Hinweis {current} von {total}"))
        text = QLabel(notice.message); text.setWordWrap(True); layout.addWidget(text)
        note = QLabel("„Ignorieren“ unterdrückt nur weitere Anzeigen dieser Meldungsart. "
            "Die Meldung bleibt im Importbericht protokolliert; keine Buchung wird verworfen.")
        note.setWordWrap(True); layout.addWidget(note)
        buttons = QDialogButtonBox()
        accept = buttons.addButton("&Übernehmen", QDialogButtonBox.ButtonRole.AcceptRole)
        ask = buttons.addButton("&Nachfragen", QDialogButtonBox.ButtonRole.ActionRole)
        ignore = buttons.addButton("&Ignorieren · aktueller Import", QDialogButtonBox.ButtonRole.ActionRole)
        future = buttons.addButton("Alle &zukünftigen ignorieren", QDialogButtonBox.ButtonRole.ActionRole)
        accept.clicked.connect(lambda: self.finish("accept"))
        ask.clicked.connect(lambda: self.finish("ask"))
        ignore.clicked.connect(lambda: self.finish("ignore"))
        future.clicked.connect(lambda: self.finish("ignore_future"))
        future.setEnabled(notice.persistable)
        future.setToolTip("Nur für stabil codierte, nichtkritische Meldungstypen verfügbar")
        accept.setDefault(True)
        layout.addWidget(buttons)

    def finish(self, action):
        self.action = action
        self.accept()


ADVANCE_TAX_FIELDS = (
    ('security_ref', 'Wertpapier / ISIN'), ('account', 'Depot'),
    ('income_year', 'Ertragsjahr'), ('advance_tax_base', 'Vorabpauschale'),
    ('taxable_income', 'Steuerpflichtiger Betrag'),
    ('partial_exemption_amount', 'Teilfreistellung'),
    ('used_exemption', 'Genutzter Freibetrag'), ('paid_taxes', 'Gezahlte Steuern'),
    ('capital_gains_tax', 'Kapitalertragsteuer'),
    ('solidarity_surcharge', 'Solidaritätszuschlag'),
    ('church_tax', 'Kirchensteuer'), ('reference_no', 'Belegreferenz'),
    ('source', 'Beleg'),
)


class AdvanceTaxConflictDialog(QDialog):
    """Explicitly skip one duplicate advance-tax fact or abort the preview."""
    def __init__(self, conflict, current, total, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Vorabpauschale bereits vorhanden')
        self.setMinimumWidth(900)
        self.action = None
        layout = QVBoxLayout(self)
        title = QLabel(f'Vorabpauschalen-Konflikt {current} von {total}')
        title.setStyleSheet('font-size: 16px; font-weight: 600')
        layout.addWidget(title)
        state = ('Wirtschaftlich identischer Reimport.' if conflict['identical'] else
                 'Die wirtschaftlichen Steuerdaten weichen ab. Bitte Unterschiede prüfen.')
        notice = QLabel(state); notice.setWordWrap(True); layout.addWidget(notice)
        table = QTableWidget(len(ADVANCE_TAX_FIELDS), 3)
        table.setHorizontalHeaderLabels(['Feld', 'Vorhanden', 'Neu'])
        for row, (field_name, label) in enumerate(ADVANCE_TAX_FIELDS):
            old = _value(conflict['old'], field_name)
            new = _value(conflict['new'], field_name)
            for column, value in enumerate((label, old, new)):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, column, item)
            if old != new:
                for column in (1, 2):
                    table.item(row, column).setBackground(QColor('#fff0bd'))
                    table.item(row, column).setForeground(QColor('#222222'))
        table.resizeColumnsToContents(); layout.addWidget(table)
        explanation = QLabel(
            'Ignorieren behält die vorhandene Vorabpauschale und überspringt nur das '
            'neue Steuerereignis. Andere Buchungen und Belege des Imports bleiben erhalten.')
        explanation.setWordWrap(True); layout.addWidget(explanation)
        buttons = QDialogButtonBox()
        ignore = buttons.addButton('&Ignorieren', QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton('&Abbrechen', QDialogButtonBox.ButtonRole.RejectRole)
        ignore.clicked.connect(lambda: self.finish('ignore'))
        cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def finish(self, action):
        self.action = action
        self.accept()


def resolve_advance_tax_conflicts_interactively(
        wizard, conflicts, dialog_class=AdvanceTaxConflictDialog):
    """Collect every decision before simulation; cancellation performs no write."""
    _require_gui_thread()
    for index, conflict in enumerate(conflicts, 1):
        saved = wizard.decisions.get(conflict['key'], {})
        if saved.get('action') == 'ignore':
            continue
        dialog = dialog_class(conflict, index, len(conflicts), wizard)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if dialog.action != 'ignore':
            return False
        wizard.decisions[conflict['key']] = {
            'action': 'ignore',
            'reason': ('Wirtschaftlich identischer Reimport ignoriert' if conflict['identical']
                       else 'Abweichende Vorabpauschale nach Sichtprüfung ignoriert'),
        }
    return True


def _require_gui_thread():
    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        raise RuntimeError("Importentscheidungen dürfen nur im GUI-Thread angezeigt werden.")


def resolve_warnings_interactively(wizard, warnings, dialog_class=WarningDecisionDialog):
    _require_gui_thread()
    policy = wizard.import_decision_policy
    persistent = getattr(wizard, "persistent_warning_rules", {})
    for index, item in enumerate(warnings, 1):
        notice = (item if isinstance(item, WarningNotice)
                  else WarningNotice(str(item), "", "generic", "", warning_kind(item), False))
        kind = notice.key or notice.category
        if notice.persistable and notice.key in persistent:
            policy.ignored_warning_count += 1
            continue
        rule = policy.warning_rules.get(kind)
        if rule in ("accept", "ignore"):
            if rule == "ignore": policy.ignored_warning_count += 1
            continue
        dialog = dialog_class(notice, index, len(warnings), wizard)
        if dialog.exec() != QDialog.DialogCode.Accepted: return False
        if dialog.action == "ask":
            continue
        if dialog.action == "ignore_future":
            if not notice.persistable:
                raise ValueError("Diese sicherheitsrelevante oder ungecodete Meldung darf nicht dauerhaft ignoriert werden.")
            persistent[notice.key] = {"plugin": notice.plugin, "code": notice.code,
                                      "category": notice.category}
            getattr(wizard, "save_persistent_warning_rules", lambda rules: None)(persistent)
            policy.ignored_warning_count += 1
            continue
        policy.warning_rules[kind] = dialog.action
        if dialog.action == "ignore": policy.ignored_warning_count += 1
    return True


def resolve_conflicts_interactively(wizard, dialog_class=BookingConflictDialog):
    _require_gui_thread()
    policy = wizard.import_decision_policy
    for row, conflict in enumerate(wizard.conflicts):
        combo = wizard.conflict_table.cellWidget(row, 0)
        if combo.currentData() is not None: continue
        if identical_conflict(conflict):
            combo.setCurrentIndex(combo.findData("skip")); continue
        kind = conflict_kind(conflict)
        action = policy.conflict_rules.get(kind)
        if action is None:
            dialog = dialog_class(conflict, row + 1, len(wizard.conflicts), wizard)
            if dialog.exec() != QDialog.DialogCode.Accepted: return False
            action = dialog.action
            if dialog.scope.currentData() == "all": policy.conflict_rules[kind] = action
        choice = combo.findData(action)
        if choice < 0: return False
        combo.setCurrentIndex(choice)
        if action == "replace":
            reason = wizard.conflict_table.cellWidget(row, 1)
            if not reason.text().strip(): reason.setText("Interaktiv bestätigter neuer Beleg")
    return True


def install_conflict_actions(wizard):
    bar = QHBoxLayout(); wizard.layout().addLayout(bar)
    for label, callback in [
        ("Für alle offenen Entscheidungen übernehmen", lambda: copy_first_decision(wizard)),
        ("Begründung für alle Ersatzentscheidungen übernehmen", lambda: copy_first_reason(wizard))]:
        button = QPushButton(label); button.clicked.connect(callback); bar.addWidget(button)


def apply_open_decisions(wizard, action):
    for row in range(wizard.conflict_table.rowCount()):
        combo = wizard.conflict_table.cellWidget(row, 0)
        index = combo.findData(action)
        if combo.currentData() is None and index >= 0: combo.setCurrentIndex(index)


def copy_first_decision(wizard):
    if not wizard.conflict_table.rowCount(): return
    action = wizard.conflict_table.cellWidget(0, 0).currentData()
    if action is None:
        QMessageBox.information(wizard, "Entscheidung übernehmen", "Bitte zuerst die erste Entscheidung auswählen.")
        return
    apply_open_decisions(wizard, action)


def copy_first_reason(wizard):
    if not wizard.conflict_table.rowCount(): return
    reason = wizard.conflict_table.cellWidget(0, 1).text().strip()
    if not reason:
        QMessageBox.information(wizard, "Begründung übernehmen", "Bitte zuerst die Begründung in der ersten Zeile eingeben.")
        return
    for row in range(1, wizard.conflict_table.rowCount()):
        editor = wizard.conflict_table.cellWidget(row, 1)
        if wizard.conflict_table.cellWidget(row, 0).currentData() == "replace" and not editor.text().strip():
            editor.setText(reason)


def ask_conflict_policy(wizard):
    """Compatibility entry point for the guided per-conflict policy."""
    return resolve_conflicts_interactively(wizard)
