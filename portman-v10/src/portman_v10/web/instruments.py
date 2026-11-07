"""Instrumentpflege der Web-Testoberfläche: Formular ↔ InstrumentInput, Speicherung über SQLiteStore."""
from dataclasses import dataclass

from portman_v10.application.contracts import ApplicationError, ErrorCode, Instrument, InstrumentInput

# Gespeicherter asset_type-Wert → Anzeige. Andere vorhandene Werte (z. B. "security" aus dem Import) bleiben lesbar.
INSTRUMENT_TYPE_LABELS = {
    "ETF": "ETF",
    "stock": "Aktie",
    "certificate": "Zertifikat",
    "etc": "ETC",
    "real_estate": "Immobilie",
    "commodity": "Rohstoff",
}


class InstrumentFormError(Exception):
    """Eingabe lässt sich nicht in einen vollständigen InstrumentInput übersetzen."""


@dataclass(frozen=True, slots=True)
class InstrumentForm:
    instrument_id: str = ""
    expected_revision: str = ""
    name: str = ""
    asset_type: str = ""
    isin: str = ""
    wkn: str = ""
    return_to: str = ""
    kept_identifiers: tuple[str, ...] = ()


def _identifier_label(value) -> str:
    return f"{value.provider}/{value.identifier_type} {value.value} ({value.context})"


def form_from_instrument(instrument: Instrument) -> InstrumentForm:
    return InstrumentForm(instrument.instrument_id, str(instrument.revision), instrument.name, instrument.asset_type,
                          instrument.isin or "", instrument.wkn or "",
                          kept_identifiers=tuple(_identifier_label(value) for value in instrument.identifiers))


def form_from_request(form, current: Instrument | None) -> InstrumentForm:
    return InstrumentForm(form.get("instrument_id", ""), form.get("expected_revision", ""), form.get("name", ""),
                          form.get("asset_type", ""), form.get("isin", ""), form.get("wkn", ""), form.get("return_to", ""),
                          tuple(_identifier_label(value) for value in current.identifiers) if current else ())


def _normalize_code(value: str) -> str | None:
    return "".join(value.split()).upper() or None


def instrument_input_from_form(form, current: Instrument | None, store) -> tuple[InstrumentInput, int | None]:
    """Vollständiger Datensatzstand; weitere Kennungen eines bestehenden Instruments bleiben unverändert."""
    instrument_id = form.get("instrument_id", "").strip() or None
    expected_revision = None
    if instrument_id:
        if current is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Instrument nicht gefunden")
        try:
            expected_revision = int(form.get("expected_revision", ""))
        except ValueError as error:
            raise InstrumentFormError("Erwartete Instrument-Revision fehlt oder ist ungültig.") from error
    asset_type = form.get("asset_type", "")
    keeps_unlisted = current is not None and asset_type == current.asset_type
    if asset_type not in INSTRUMENT_TYPE_LABELS and not keeps_unlisted:
        raise InstrumentFormError("Bitte eine Art aus der Auswahlliste wählen.")
    isin, wkn = _normalize_code(form.get("isin", "")), _normalize_code(form.get("wkn", ""))
    if not isin and not wkn:
        raise InstrumentFormError("ISIN oder WKN ist erforderlich; der Import ordnet nur über diese Kennungen zu.")
    # Doppelte Standardkennungen machen die Importzuordnung mehrdeutig. Prüfung über die vorhandene Kennungssuche.
    for identifier_type, value in (("ISIN", isin), ("WKN", wkn)):
        if value:
            others = [match for match in store.match_instrument_identifier(identifier_type, "standard", value) if match != instrument_id]
            if others:
                raise InstrumentFormError(f"{identifier_type} {value} gehört bereits zu einem anderen Instrument.")
    try:
        value = InstrumentInput(form.get("name", "").strip(), asset_type, isin, wkn, instrument_id,
                                current.identifiers if current else ())
    except ValueError as error:
        raise InstrumentFormError(str(error)) from error
    return value, expected_revision


def safe_return_path(value: str) -> str | None:
    """Nur lokale Importseiten als Rücksprung zulassen (kein offener Redirect)."""
    return value if value.startswith("/jobs/") and "//" not in value and "\\" not in value else None
