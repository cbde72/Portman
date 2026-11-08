import os
from pathlib import Path
import re
import sys
from typing import get_args, get_type_hints

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from portman_v10.application.contracts import InstrumentInput
from portman_v10.infrastructure.sqlite_store import SQLiteStore


def main():
    profile = Path(os.environ.get("PORTMAN_V10_WEB_DATA") or "data/web-test")
    database = (root / profile / "v10.sqlite").resolve()
    print(f"Datenbank: {database}")

    if not database.is_file():
        raise SystemExit("Datenbank fehlt. Starte zuerst das V10-Web-Testprofil.")

    isin = "".join(input("ISIN: ").split()).upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        raise SystemExit("Die ISIN muss 12 Zeichen haben, z. B. DE0007164600.")

    store = SQLiteStore(database)
    matches = store.match_instrument_identifier("ISIN", "standard", isin)

    if len(matches) > 1:
        raise SystemExit("Die ISIN ist mehrfach hinterlegt. Bitte Zuordnung prüfen.")
    if matches:
        item = store.get_instrument(matches[0])
        print(f"Bereits vorhanden: {item.name} | {item.isin} | ID: {item.instrument_id}")
        return

    name = input("Wertpapiername: ").strip()
    wkn = input("WKN (optional): ").strip().upper() or None
    if not name:
        raise SystemExit("Bitte einen Wertpapiernamen eingeben.")

    types = get_args(get_type_hints(InstrumentInput).get("asset_type", str))
    if types:
        print("Anlagearten:", ", ".join(map(str, types)))
    asset_type = input("Anlageart (z. B. fund für einen ETF): ").strip()
    if not asset_type or (types and asset_type not in types):
        raise SystemExit("Bitte eine gültige Anlageart eingeben.")

    if wkn and store.match_instrument_identifier("WKN", "standard", wkn):
        raise SystemExit("Diese WKN ist bereits hinterlegt. Bitte bestehendes Instrument prüfen.")

    item = store.save_instrument(
        InstrumentInput(name, asset_type, isin=isin, wkn=wkn)
    )
    print(f"Angelegt: {item.name} | {item.isin} | ID: {item.instrument_id}")


if __name__ == "__main__":
    main()