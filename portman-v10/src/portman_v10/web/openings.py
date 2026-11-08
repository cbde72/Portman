"""Eröffnungsbestand in der Web-Testoberfläche: Formular → OpeningBalanceInput (Prüfung in Vertrag und Store)."""
from datetime import date

from portman_v10.application.contracts import Account, OpeningBalanceInput
from portman_v10.domain.values import ExactValue, canonical_decimal


class OpeningFormError(Exception):
    """Eingabe lässt sich nicht in einen OpeningBalanceInput übersetzen."""


def exact_from_text(raw: str, label: str, *, required: bool) -> ExactValue | None:
    """Exakter Dezimalwert aus der Eingabe; Komma als Dezimaltrennzeichen, keine Tausendertrennzeichen, kein Float."""
    text = "".join(raw.split())
    if not text:
        if required:
            raise OpeningFormError(f"{label} ist erforderlich.")
        return None
    if "," in text and "." in text:
        raise OpeningFormError(f"{label}: bitte ohne Tausendertrennzeichen eingeben, z. B. 1234,56.")
    try:
        return ExactValue(canonical_decimal(text.replace(",", ".")))
    except ValueError as error:
        raise OpeningFormError(f"{label}: „{raw.strip()}“ ist kein gültiger Dezimalwert.") from error


def date_from_text(raw: str, label: str, *, required: bool) -> date | None:
    text = raw.strip()
    if not text:
        if required:
            raise OpeningFormError(f"{label} ist erforderlich.")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise OpeningFormError(f"{label}: Datum im Format JJJJ-MM-TT angeben.") from error


def opening_input_from_form(form, account: Account) -> OpeningBalanceInput:
    opening_id = form.get("opening_id", "").strip()
    effective_date = date_from_text(form.get("effective_date", ""), "Stichtag", required=True)
    note = form.get("note", "").strip() or None
    try:
        if account.kind == "cash":
            # Währung kommt vom Konto; der Store prüft die Übereinstimmung erneut.
            return OpeningBalanceInput(opening_id, account.account_id, effective_date, currency=account.currency,
                                       amount=exact_from_text(form.get("amount", ""), "Betrag", required=True), note=note)
        cost = exact_from_text(form.get("acquisition_cost", ""), "Anschaffungskosten", required=False)
        return OpeningBalanceInput(
            opening_id, account.account_id, effective_date,
            instrument_id=form.get("instrument_id", "").strip() or None,
            quantity=exact_from_text(form.get("quantity", ""), "Stückzahl", required=True),
            acquired_on=date_from_text(form.get("acquired_on", ""), "Anschaffungsdatum", required=False),
            acquisition_cost=cost,
            cost_currency=(form.get("cost_currency", "").strip().upper() or None) if cost is not None else None,
            note=note,
        )
    except ValueError as error:
        raise OpeningFormError(str(error)) from error
