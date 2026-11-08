"""Konten für das lokale Portman-V10-Web-Testprofil anlegen."""
import os
from pathlib import Path
import sys
import traceback
from datetime import date as DateType

ROOT = Path(__file__).resolve().parent


def database_path():
    profile = Path(os.environ.get("PORTMAN_V10_WEB_DATA") or "data/web-test")
    return (ROOT / profile / "v10.sqlite").resolve()


def save_accounts(subtype, iban_text, depot_text):
    from portman_v10.application.contracts import AccountIdentifier, AccountInput
    from portman_v10.infrastructure.sqlite_store import SQLiteStore

    iban = "".join(iban_text.split()).upper()
    depot_number = depot_text.strip()
    if not iban or not depot_number:
        raise ValueError("Bitte IBAN und Depotnummer eingeben.")

    database = database_path()
    if not database.is_file():
        raise ValueError(f"Datenbank fehlt. Starte zuerst das V10-Web-Testprofil.\n{database}")
    store = SQLiteStore(database)

    def find_account(identifier_type, value):
        matches = store.match_account_identifier(identifier_type, None, value)
        if not matches:
            return None
        scoped = store.match_account_identifier(identifier_type, "comdirect", value)
        if len(matches) != 1 or scoped != matches:
            raise ValueError(f"Kennung {identifier_type} ist mehrdeutig oder gehört zu einem anderen Bankkontext.")
        return store.get_account(matches[0])

    cash = find_account("iban", iban)
    depot = find_account("depot_number", depot_number)

    if cash is not None and (cash.kind, cash.subtype, cash.currency) != ("cash", subtype, "EUR"):
        raise ValueError("Das vorhandene Geldkonto hat einen anderen Kontotyp oder eine andere Währung.")
    if depot is not None:
        if depot.kind != "position" or depot.subtype != "depot":
            raise ValueError("Die Depotnummer gehört zu einem Konto mit anderem Typ.")
        if cash is None or depot.reference_account_id != cash.account_id:
            raise ValueError("Das vorhandene Depot ist nicht mit dem eingegebenen Geldkonto verknüpft.")

    notes = []
    if cash is None:
        name = "comdirect Giro" if subtype == "checking" else "comdirect Verrechnung"
        cash = store.save_account(AccountInput(
            name=name, kind="cash", subtype=subtype, institution="comdirect", currency="EUR",
            identifiers=(AccountIdentifier("iban", "comdirect", iban),),
        ))
        notes.append(f"Geldkonto angelegt: {cash.name}")
    else:
        notes.append(f"Geldkonto vorhanden: {cash.name}")

    if depot is None:
        try:
            depot = store.save_account(AccountInput(
                name="comdirect Depot", kind="position", subtype="depot", institution="comdirect",
                reference_account_id=cash.account_id,
                identifiers=(AccountIdentifier("depot_number", "comdirect", depot_number),),
            ))
        except Exception as exc:
            raise RuntimeError(
                f"Geldkonto vorhanden. Depot konnte nicht gespeichert werden.\n{exc}"
            ) from exc
        notes.append(f"Depot angelegt: {depot.name}")
    else:
        notes.append(f"Depot vorhanden: {depot.name}")

    return "\n".join((*notes, f"Referenzkonto: {cash.name}", f"Datenbank: {database}"))


def main():
    src = ROOT / "src"
    if not (src / "portman_v10").is_dir():
        raise SystemExit("Lege diese Datei im V10-Paketordner neben pyproject.toml ab.")
    sys.path.insert(0, str(src))
    try:
        from PyQt6.QtWidgets import (
            QApplication, QComboBox, QLabel, QLineEdit, QMessageBox,
            QPushButton, QVBoxLayout, QWidget,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "PyQt6":
            raise
        raise SystemExit("PyQt6 fehlt. Installiere es mit dem Python der V10-.venv.") from exc

    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Portman V10 – Konten anlegen")
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel(f"Datenbank: {database_path()}"))
    layout.addWidget(QLabel("Typ des Geldkontos"))
    kind = QComboBox()
    kind.addItem("Girokonto", "checking")
    kind.addItem("Verrechnungskonto", "settlement")
    layout.addWidget(kind)
    layout.addWidget(QLabel("IBAN des Geldkontos"))
    iban = QLineEdit()
    layout.addWidget(iban)
    layout.addWidget(QLabel("Depotnummer laut Beleg"))
    depot = QLineEdit()
    layout.addWidget(depot)
    button = QPushButton("Konten speichern")
    layout.addWidget(button)

    def submit():
        try:
            result = save_accounts(kind.currentData(), iban.text(), depot.text())
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(window, "Speichern fehlgeschlagen", str(exc))
        else:
            QMessageBox.information(window, "Konten geprüft", result)

    button.clicked.connect(submit)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
