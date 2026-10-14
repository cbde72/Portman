from PySide6.QtCore import QDate
from PySide6.QtWidgets import QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit
from portfolio_v5.models import Decimal, correction_number


class CostSplitDialog(QDialog):
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle('Kaufwert oder Aktiensplit nachtragen')
        self.setMinimumWidth(650)
        self.form = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItem('Gesamtkaufwert nachtragen', 'cost')
        self.mode.addItem('Aktiensplit / Zusammenlegung', 'split')
        self.form.addRow('Nachtrag', self.mode)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat('dd.MM.yyyy')
        self.form.addRow('Stichtag / Splitdatum', self.day)
        self.position = QComboBox()
        self.form.addRow('Depot und Wertpapier', self.position)
        self.units = QLabel()
        self.form.addRow('Bestand', self.units)
        self.cost = QLineEdit()
        self.cost.setPlaceholderText('Gesamter Kaufwert einschließlich Kosten, kein Stückpreis')
        self.form.addRow('Gesamtkaufwert in Bestandswährung', self.cost)
        self.old = QLineEdit('1')
        self.new = QLineEdit('10')
        self.form.addRow('Alte Stücke im Verhältnis', self.old)
        self.form.addRow('Neue Stücke im Verhältnis', self.new)
        self.source = QLineEdit()
        self.source.setPlaceholderText('Belegname, Datum oder nachvollziehbare Erläuterung')
        self.form.addRow('Beleg / Notiz', self.source)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.form.addRow(self.hint)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.form.addRow(buttons)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.day.dateChanged.connect(self.refresh)
        self.position.currentIndexChanged.connect(self.show_position)
        self.old.textChanged.connect(self.show_position)
        self.new.textChanged.connect(self.show_position)
        self.refresh()

    def refresh(self):
        previous = self.position.currentData()
        split = self.mode.currentData() == 'split'
        self.form.setRowVisible(self.cost, not split)
        self.form.setRowVisible(self.old, split)
        self.form.setRowVisible(self.new, split)
        day = self.day.date().addDays(-1) if split else self.day.date()
        self.positions = self.repo.holdings(day.toString('yyyy-MM-dd'))
        self.position.blockSignals(True)
        self.position.clear()
        for p in self.positions:
            self.position.addItem(f"{p['depot']} · {p['name']} · {p['key']}", (p['depot'], p['key']))
        index = self.position.findData(previous)
        if index >= 0:
            self.position.setCurrentIndex(index)
        self.position.blockSignals(False)
        self.show_position()

    def show_position(self):
        index = self.position.currentIndex()
        if index < 0:
            self.units.setText('Kein gespeicherter Bestand an diesem Datum.')
            return
        p = self.positions[index]
        self.units.setText(f"{p['quantity']} Stück · {p['currency']} · Bestandsdatum {p.get('as_of') or p['period']}")
        if self.mode.currentData() == 'cost':
            self.hint.setText('Der Kaufwert gilt für den angezeigten gespeicherten Bestand und dessen Datum. '
                'Für einen fehlenden Anfangseinstand den damaligen Stichtag wählen. Spätere Käufe und Splits werden fortgeschrieben.')
        else:
            self.hint.setText('Beispiel: 1 alte → 10 neue Stücke. Der Gesamtkaufwert bleibt gleich. '
                'Die Maßnahme gilt vor den Käufen/Verkäufen dieses Tages; spätere Bankbestände werden nicht erneut vervielfacht.')
            try:
                ratio = self.ratio()
                if p.get('quantity') is not None:
                    self.hint.setText(self.hint.text() + f" Ergebnis: {Decimal(p['quantity']) * ratio} Stück.")
            except (ValueError, ArithmeticError):
                pass

    def ratio(self):
        old = Decimal(correction_number(self.old.text()) or '0')
        new = Decimal(correction_number(self.new.text()) or '0')
        if not old.is_finite() or not new.is_finite() or old <= 0 or new <= 0 or old == new:
            raise ValueError('Positive, unterschiedliche Stückzahlen für das Verhältnis angeben.')
        return new / old

    def accept(self):
        try:
            if self.position.currentIndex() < 0:
                raise ValueError('Einen vorhandenen Bestand auswählen.')
            p = self.positions[self.position.currentIndex()]
            if not self.source.text().strip():
                raise ValueError('Bitte eine Belegquelle oder Notiz angeben.')
            if self.mode.currentData() == 'cost':
                if p.get('snapshot_id') is None or p.get('date_basis') == 'transactions':
                    raise ValueError('Für den Kaufwert einen gespeicherten Depotstand vor der Fortschreibung auswählen.')
                self.repo.correct_cost(p['snapshot_id'], p['key'], correction_number(self.cost.text()), self.source.text())
            else:
                day = self.day.date().toString('yyyy-MM-dd')
                if any(a['day'] == day and a['depot'] == p['depot'] and a['security'] == p['key']
                       for a in self.repo.actions('0001-01-01', day)):
                    raise ValueError('Für diesen Tag ist bereits eine Maßnahme gespeichert. Diese unter Kapitalmaßnahmen prüfen.')
                self.repo.add_action(day, p['depot'], p['key'], 'SPLIT', self.source.text(), ratio=str(self.ratio()))
        except (ValueError, TypeError, ArithmeticError) as error:
            self.error.setText(str(error))
            return
        super().accept()
