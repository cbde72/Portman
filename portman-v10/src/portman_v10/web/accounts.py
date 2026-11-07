"""Kontenpflege der Web-Testoberfläche: Formular ↔ AccountInput, Speicherung über SQLiteStore."""
from dataclasses import dataclass

from portman_v10.application.contracts import Account, AccountIdentifier, AccountInput, ApplicationError, ErrorCode

# Formulartyp → (kind, subtype, Anzeige). Nur diese drei Arten werden in der Maske gepflegt.
FORM_TYPES = {
    "checking": ("cash", "checking", "Girokonto"),
    "settlement": ("cash", "settlement", "Verrechnungskonto"),
    "depot": ("position", "depot", "Depot"),
}
SUBTYPE_LABELS = {
    "checking": "Girokonto",
    "savings": "Tagesgeld",
    "fixed_term": "Festgeld",
    "settlement": "Verrechnungskonto",
    "depot": "Depot",
    "crypto": "Kryptokonto",
}
IDENTIFIER_LABELS = {"iban": "IBAN", "depot_number": "Depotnummer", "account_number": "Kontonummer"}


class AccountFormError(Exception):
    """Eingabe lässt sich nicht in einen vollständigen AccountInput übersetzen."""


@dataclass(frozen=True, slots=True)
class AccountForm:
    """Vorbelegung der Eingabemaske; Werte stammen aus Konto oder abgesendetem Formular."""
    form_type: str
    account_id: str = ""
    expected_revision: str = ""
    name: str = ""
    institution: str = ""
    currency: str = "EUR"
    iban: str = ""
    depot_number: str = ""
    reference_account_id: str = ""
    kept: tuple[tuple[int, str, bool], ...] = ()  # (Index, Anzeige, angehakt)

    @property
    def is_cash(self) -> bool:
        return FORM_TYPES[self.form_type][0] == "cash"


def primary_identifier_type(kind: str) -> str:
    return "iban" if kind == "cash" else "depot_number"


def _split_identifiers(account: Account):
    """Trennt die in der Maske editierbare Hauptkennung von allen übrigen beizubehaltenden Kennungen."""
    primary_type = primary_identifier_type(account.kind)
    primary = next((item for item in account.identifiers if item.identifier_type.casefold() == primary_type), None)
    others = tuple(item for item in account.identifiers if item is not primary)
    return primary, others


def identifier_label(item: AccountIdentifier) -> str:
    return f"{IDENTIFIER_LABELS.get(item.identifier_type.casefold(), item.identifier_type)} {item.value} ({item.context})"


def form_type_of(account: Account) -> str | None:
    return next((key for key, (kind, subtype, _label) in FORM_TYPES.items() if (kind, subtype) == (account.kind, account.subtype)), None)


def form_from_account(account: Account) -> AccountForm:
    form_type = form_type_of(account)
    if form_type is None:
        raise AccountFormError(f"{SUBTYPE_LABELS.get(account.subtype, account.subtype)} wird in dieser Maske nicht bearbeitet.")
    primary, others = _split_identifiers(account)
    return AccountForm(
        form_type=form_type,
        account_id=account.account_id,
        expected_revision=str(account.revision),
        name=account.name,
        institution=account.institution or "",
        currency=account.currency or "",
        iban=primary.value if primary and account.kind == "cash" else "",
        depot_number=primary.value if primary and account.kind == "position" else "",
        reference_account_id=account.reference_account_id or "",
        kept=tuple((index, identifier_label(item), True) for index, item in enumerate(others)),
    )


def form_from_request(form, current: Account | None) -> AccountForm:
    """Abgesendete Werte für eine erneute Anzeige nach Fehlern."""
    form_type = form.get("account_type", "")
    if form_type not in FORM_TYPES:
        form_type = "checking"
    checked = set(form.getlist("keep_identifier"))
    kept = ()
    if current is not None:
        _primary, others = _split_identifiers(current)
        kept = tuple((index, identifier_label(item), str(index) in checked) for index, item in enumerate(others))
    return AccountForm(
        form_type=form_type,
        account_id=form.get("account_id", ""),
        expected_revision=form.get("expected_revision", ""),
        name=form.get("name", ""),
        institution=form.get("institution", ""),
        currency=form.get("currency", ""),
        iban=form.get("iban", ""),
        depot_number=form.get("depot_number", ""),
        reference_account_id=form.get("reference_account_id", ""),
        kept=kept,
    )


def account_input_from_form(form, current: Account | None) -> tuple[AccountInput, int | None]:
    """Übersetzt das Formular in einen vollständigen Datensatzstand samt erwarteter Revision.

    Fachliche Prüfung erfolgt in AccountInput und SQLiteStore.save_account; hier wird nur
    die Eingabe in die Vertragsform gebracht.
    """
    form_type = form.get("account_type", "")
    if form_type not in FORM_TYPES:
        raise AccountFormError("Bitte Girokonto, Verrechnungskonto oder Depot wählen.")
    kind, subtype, _label = FORM_TYPES[form_type]
    account_id = form.get("account_id", "").strip() or None
    expected_revision = None
    identifiers: list[AccountIdentifier] = []
    if account_id:
        if current is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Konto nicht gefunden")
        try:
            expected_revision = int(form.get("expected_revision", ""))
        except ValueError as error:
            raise AccountFormError("Erwartete Konto-Revision fehlt oder ist ungültig.") from error
        if expected_revision != current.revision:
            # Indizes der beizubehaltenden Kennungen beziehen sich auf den angezeigten Stand.
            raise ApplicationError(ErrorCode.STALE_REVISION, "Konto-Revision ist veraltet; bitte Konto neu laden.")
        _primary, others = _split_identifiers(current)
        for raw in form.getlist("keep_identifier"):
            try:
                index = int(raw)
            except ValueError as error:
                raise AccountFormError("Ungültige Kennungsauswahl.") from error
            if not 0 <= index < len(others):
                raise AccountFormError("Ungültige Kennungsauswahl.")
            identifiers.append(others[index])

    institution = form.get("institution", "").strip() or None
    if kind == "cash":
        currency = form.get("currency", "").strip().upper() or None
        primary_value = "".join(form.get("iban", "").split()).upper()
        reference_account_id = None
    else:
        currency = None
        primary_value = form.get("depot_number", "").strip()
        reference_account_id = form.get("reference_account_id", "").strip() or None
    if primary_value:
        if not institution:
            label = "IBAN" if kind == "cash" else "Depotnummer"
            raise AccountFormError(f"Für die {label} wird die Bank als Kennungskontext benötigt.")
        # Kontext wie im Parseradapter: Bankname, Vergleich ohne Groß-/Kleinschreibung.
        identifiers.append(AccountIdentifier(primary_identifier_type(kind), institution.casefold(), primary_value))
    identifiers = list(dict.fromkeys(identifiers))
    try:
        value = AccountInput(
            name=form.get("name", "").strip(),
            kind=kind,
            subtype=subtype,
            institution=institution,
            currency=currency,
            reference_account_id=reference_account_id,
            account_id=account_id,
            identifiers=tuple(identifiers),
        )
    except ValueError as error:
        raise AccountFormError(str(error)) from error
    return value, expected_revision


def account_rows(accounts: tuple[Account, ...]):
    names = {account.account_id: account.name for account in accounts}
    rows = []
    for account in sorted(accounts, key=lambda item: (not item.active, item.kind, item.name.casefold(), item.account_id)):
        rows.append({
            "account_id": account.account_id,
            "name": account.name,
            "type": SUBTYPE_LABELS.get(account.subtype, account.subtype),
            "institution": account.institution or "Unbekannt",
            "currency": account.currency or "–",
            "identifiers": tuple(identifier_label(item) for item in account.identifiers),
            "reference": names.get(account.reference_account_id, "Konto nicht verfügbar") if account.reference_account_id else "–",
            "active": account.active,
            "revision": account.revision,
            "editable": form_type_of(account) is not None,
        })
    return tuple(rows)


def reference_options(accounts: tuple[Account, ...], exclude_id: str | None = None):
    return tuple(
        (account.account_id, f"{account.name} · {SUBTYPE_LABELS.get(account.subtype, account.subtype)}{'' if account.active else ' · deaktiviert'}")
        for account in sorted(accounts, key=lambda item: item.name.casefold())
        if account.kind == "cash" and account.account_id != exclude_id
    )
