"""Ausführbarer synthetischer Ablauf für Stammdaten und Eröffnungsbestände."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date

from portman_v10.application.contracts import AccountInput, InstrumentIdentifier, InstrumentInput, OpeningBalanceInput
from portman_v10.domain.values import ExactValue
from portman_v10.infrastructure.sqlite_store import SQLiteStore


def run_demo(database_path: Path) -> str:
    store = SQLiteStore(database_path)
    store.migrate()
    giro = store.save_account(AccountInput("Demo Giro", "cash", "checking", institution="Beispielbank", currency="EUR"))
    savings = store.save_account(AccountInput("Demo Tagesgeld", "cash", "savings", institution="Beispielbank", currency="EUR"))
    depot = store.save_account(AccountInput("Demo Depot", "position", "depot", institution="Beispielbank", reference_account_id=giro.account_id))
    wallet = store.save_account(AccountInput("Demo Kryptokonto", "position", "crypto", institution="Demo Network"))
    fund = store.save_instrument(InstrumentInput(
        "Synthetischer Beispiel-ETF", "fund", isin="DE0000000001",
        identifiers=(InstrumentIdentifier("demo-market-data", "ticker", "XETRA", "DEMO"),),
    ))
    coin = store.save_instrument(InstrumentInput(
        "Synthetischer Beispiel-Coin", "cryptoasset",
        identifiers=(InstrumentIdentifier("demo-network", "network_asset", "testnet-1", "DEMOCOIN"),),
    ))
    store.record_opening(OpeningBalanceInput("demo-opening-giro", giro.account_id, date(2025, 1, 1), currency="EUR", amount=ExactValue("1000.25")))
    store.record_opening(OpeningBalanceInput("demo-opening-savings", savings.account_id, date(2025, 1, 1), currency="EUR", amount=ExactValue("250")))
    store.record_opening(OpeningBalanceInput("demo-opening-fund", depot.account_id, date(2025, 1, 1), instrument_id=fund.instrument_id, quantity=ExactValue("2"), acquired_on=date(2023, 6, 15), acquisition_cost=ExactValue("103"), cost_currency="EUR"))
    store.record_opening(OpeningBalanceInput("demo-opening-coin", wallet.account_id, date(2025, 1, 1), instrument_id=coin.instrument_id, quantity=ExactValue("0.000000000000000123")))

    # Neue Store-Instanz: alle gelesenen Werte kommen nach dem Datei-Neuöffnen aus SQLite.
    reopened = SQLiteStore(database_path)
    actual_accounts = {item.name: item for item in reopened.list_accounts().items}
    actual_instruments = {item.instrument_id: item for item in (reopened.get_instrument(fund.instrument_id), reopened.get_instrument(coin.instrument_id))}
    actual_openings = {key: reopened.get_opening(key) for key in (
        "demo-opening-giro", "demo-opening-savings", "demo-opening-fund", "demo-opening-coin",
    )}

    rows = ["Portman V10 - synthetische Stammdaten-/Eroeffnungspruefung", "Datenbank: temporaer; nach Ende des Beispiels geloescht", ""]
    expected = {
        "demo-opening-giro": "1000.25 EUR",
        "demo-opening-savings": "250 EUR",
        "demo-opening-fund": "2 Stueck; Anschaffungskosten 103 EUR; Anschaffungsdatum 2023-06-15",
        "demo-opening-coin": "0.000000000000000123 DEMOCOIN; Anschaffungskosten unbekannt",
    }
    for opening_id, expected_value in expected.items():
        item = actual_openings[opening_id]
        if item.amount is not None:
            actual_value = f"{item.amount.text} {item.currency}"
        elif item.cost_basis_status == "unknown":
            symbol = actual_instruments[item.instrument_id].identifiers[0].value
            actual_value = f"{item.quantity.text} {symbol}; Anschaffungskosten unbekannt"
        else:
            actual_value = f"{item.quantity.text} Stueck; Anschaffungskosten {item.acquisition_cost.text} {item.cost_currency}; Anschaffungsdatum {item.acquired_on.isoformat()}"
        rows.append(f"{opening_id}: erwartet: {expected_value} | tatsachlich: {actual_value} | {'OK' if actual_value == expected_value else 'ABWEICHUNG'}")
    rows.extend((
        "", f"Konten nach Neuoeffnung: {len(actual_accounts)} (Giro, Tagesgeld, Depot, Kryptokonto)",
        f"Instrumente nach Neuoeffnung: {len(actual_instruments)} (Wertpapier und Coin)",
        "Historienhinweis: Eroeffnungen sind manuelle Startbestaende, keine vollstaendige fruehere Historie.",
        "Indexhinweis: Bestandsindex wird hier nicht gepflegt; aus ihm wird kein Bestand ausgegeben.",
    ))
    return "\n".join(rows)


def main() -> None:
    with TemporaryDirectory(prefix="portman-v10-demo-") as directory:
        print(run_demo(Path(directory) / "master-data-demo.sqlite"))


if __name__ == "__main__":
    main()
