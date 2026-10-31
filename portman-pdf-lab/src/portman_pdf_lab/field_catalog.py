"""Versioned YAML field catalogs mapped to public parser DTO paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

import yaml


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    path: str
    label: str
    description: str
    data_type: str = "TEXT"
    format: str = ""
    unit: str = ""
    requirement: str = "OPTIONAL"
    validation: str = ""
    editor: str = "TEXT"
    order: int = 100
    visible: bool = True
    patterns: tuple[str, ...] = ()
    normalizers: tuple[str, ...] = ("TEXT",)
    evidence_required: bool = True
    missing_behavior: str = "Als fehlend/prüfpflichtig anzeigen"
    condition: dict[str, Any] | None = None
    example: str = ""
    pdf_source: str = ""
    available_rules: tuple[str, ...] = ("STANDARD", "EXTENDED")


TRADE_FIELDS = (
    FieldDefinition("security.isin", "events[0].trades[0].isin", "ISIN", "Internationale Wertpapierkennung", "ISIN", "12 Zeichen", requirement="CONDITIONAL", validation=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$", editor="ISIN", order=10, condition={"op":"REQUIRED_UNLESS_VALID","paths":["events[0].trades[0].wkn","events[0].trades[0].security_name"]}),
    FieldDefinition("security.wkn", "events[0].trades[0].wkn", "WKN", "Deutsche Wertpapierkennnummer", "WKN", "6 Zeichen", requirement="CONDITIONAL", validation=r"^[A-Z0-9]{6}$", editor="WKN", order=20, condition={"op":"REQUIRED_UNLESS_VALID","paths":["events[0].trades[0].isin","events[0].trades[0].security_name"]}),
    FieldDefinition("security.name", "events[0].trades[0].security_name", "Wertpapiername", "Bezeichnung des Wertpapiers", requirement="REQUIRED", order=30),
    FieldDefinition("trade.quantity", "events[0].trades[0].quantity", "Stückzahl", "Gehandelte Stückzahl ohne Rundung", "DECIMAL", editor="DECIMAL", requirement="REQUIRED", normalizers=("DECIMAL_DE", "DECIMAL_EN"), order=40),
    FieldDefinition("trade.date", "events[0].trades[0].trade_date", "Geschäftsdatum", "Gedrucktes Geschäftsdatum", "DATE", requirement="REQUIRED", editor="DATE", normalizers=("DATE_DE", "DATE_ISO"), order=45),
    FieldDefinition("trade.price", "events[0].trades[0].price", "Kurs", "Gedruckter Transaktionskurs", "DECIMAL", editor="AMOUNT", requirement="CONDITIONAL", condition={"op":"PRESENT","path":"events[0].trades[0].price_currency"}, normalizers=("DECIMAL_DE", "DECIMAL_EN"), order=50),
    FieldDefinition("trade.market_value", "events[0].trades[0].market_value", "Kurswert", "Gedruckter Kurswert; nie willkürlich berechnen", "DECIMAL", editor="AMOUNT", requirement="CONDITIONAL", condition={"op":"PRESENT","path":"events[0].trades[0].market_value"}, normalizers=("DECIMAL_DE", "DECIMAL_EN"), order=55),
    FieldDefinition("trade.amount", "events[0].cash_movements[0].amount", "Settlement", "Tatsächlicher oder erwarteter Geldbetrag gemäß Status", "DECIMAL", editor="AMOUNT", requirement="REQUIRED", normalizers=("DECIMAL_DE", "DECIMAL_EN"), order=60),
    FieldDefinition("trade.currency", "events[0].cash_movements[0].currency", "Settlement-Währung", "Ausgewiesene Währung", requirement="REQUIRED", order=65),
    FieldDefinition("trade.fees", "events[0].fee_events", "Gebühren", "Ausgewiesene Gebühren; leer ist zulässig, wenn nicht gedruckt", "LIST", requirement="OPTIONAL", order=70),
    FieldDefinition("trade.venue", "attributes.user_fields.trade.venue", "Handelsplatz", "Optionaler Ausführungs- oder Handelsplatz", "TEXT", requirement="OPTIONAL", editor="VENUE", patterns=("Handelsplatz", "Ausführungsplatz"), order=80),
)

TECHNICAL_FIELDS = (
    FieldDefinition("technical.parser", "plugin_id", "Parser-ID", "Technisch ausgewählter Parser", requirement="TECHNICAL", editor="STATUS", evidence_required=False, order=900),
    FieldDefinition("technical.evidence", "evidence", "Evidence", "PDF-Fundstellen der Erkennung", "MULTILINE", requirement="TECHNICAL", editor="MULTILINE", evidence_required=False, order=910),
)

ACCOUNT_FIELDS = (
    FieldDefinition("account.id", "accounts[0].account_id", "Konto", "Kontokennung", requirement="REQUIRED", order=10),
    FieldDefinition("account.iban", "accounts[0].iban.value", "IBAN", "Internationale Kontokennung", "IBAN", requirement="OPTIONAL", validation=r"^[A-Z]{2}[0-9A-Z]{13,32}$", editor="IBAN", order=20),
    FieldDefinition("booking.date", "events[0].event_date", "Buchungsdatum", "Datum der Kontobuchung", "DATE", requirement="REQUIRED", editor="DATE", order=30),
    FieldDefinition("booking.amount", "events[0].cash_movements[0].amount", "Betrag", "Gebuchter Betrag", "DECIMAL", requirement="REQUIRED", editor="AMOUNT", order=40),
    FieldDefinition("booking.currency", "events[0].cash_movements[0].currency", "Währung", "Buchungswährung", requirement="REQUIRED", order=50),
    FieldDefinition("booking.value_date", "attributes.user_fields.booking.value_date", "Valuta", "Optionales Valutadatum", "DATE", requirement="OPTIONAL", editor="DATE", order=60),
)

DEPOT_FIELDS = (
    FieldDefinition("depot.id", "depots[0].depot_id", "Depot", "Depotidentifikation", requirement="REQUIRED", order=10),
    FieldDefinition("snapshot.date", "depot_snapshots[0].as_of.value", "Stichtag", "Stichtag der Aufstellung", "DATE", requirement="REQUIRED", editor="DATE", order=20),
    FieldDefinition("position.security", "depot_snapshots[0].positions[0].security_id.value", "Wertpapier", "Positionsidentifikation", requirement="REQUIRED", order=30),
    FieldDefinition("position.quantity", "depot_snapshots[0].positions[0].quantity.value", "Bestand", "Bestandsstückzahl, keine Kauftransaktion", "DECIMAL", requirement="REQUIRED", editor="DECIMAL", order=40),
    FieldDefinition("position.market_value", "depot_snapshots[0].positions[0].market_value.value", "Marktwert", "Ausgewiesener Positionswert", "DECIMAL", requirement="OPTIONAL", editor="AMOUNT", order=50),
)

MIFID_FIELDS = (
    FieldDefinition("mifid.type", "events[0].cost_events[0].information_type", "Kosteninformationstyp", "MiFID-II ex ante oder ex post", requirement="REQUIRED", order=10),
    FieldDefinition("mifid.category", "events[0].cost_events[0].kind", "Kostenkategorie", "Ausgewiesene Kostenkategorie", requirement="REQUIRED", order=20),
    FieldDefinition("mifid.amount", "events[0].cost_events[0].amount", "Informationsbetrag", "Informatorischer Betrag ohne Cashflowwirkung", "DECIMAL", requirement="REQUIRED", editor="AMOUNT", order=30),
    FieldDefinition("mifid.currency", "events[0].cost_events[0].currency", "Währung", "Währung der Kosteninformation", requirement="REQUIRED", order=40),
)

TAX_FIELDS = (
    FieldDefinition("tax.isin", "events[0].tax_events[0].isin", "ISIN", "Wertpapierzuordnung", "ISIN", requirement="REQUIRED", editor="ISIN", order=10),
    FieldDefinition("tax.year", "events[0].tax_events[0].tax_year", "Steuerjahr", "Ausgewiesenes Steuerjahr", "INTEGER", requirement="REQUIRED", order=20),
    FieldDefinition("tax.basis", "events[0].tax_events[0].assessment_basis", "Bemessungsgrundlage", "Tatsächlich ausgewiesene steuerliche Größe", "DECIMAL", requirement="CONDITIONAL", condition={"op":"PRESENT","path":"events[0].tax_events[0].assessment_basis"}, editor="AMOUNT", order=30),
    FieldDefinition("tax.withheld", "events[0].tax_events[0].actually_withheld_tax", "Einbehaltene Steuer", "Tatsächlich ausgewiesene Belastung; keine künstliche Buchung", "DECIMAL", requirement="OPTIONAL", editor="AMOUNT", order=40),
)

DIVIDEND_FIELDS = (
    FieldDefinition("security.isin", "events[0].trades[0].isin", "ISIN", "Wertpapieridentifikation", "ISIN", requirement="CONDITIONAL", condition={"op":"REQUIRED_UNLESS_VALID","paths":["events[0].trades[0].wkn","events[0].trades[0].security_name"]}, editor="ISIN", order=10),
    FieldDefinition("security.wkn", "events[0].trades[0].wkn", "WKN", "Alternative Wertpapieridentifikation", "WKN", requirement="CONDITIONAL", condition={"op":"REQUIRED_UNLESS_VALID","paths":["events[0].trades[0].isin","events[0].trades[0].security_name"]}, editor="WKN", order=20),
    FieldDefinition("payment.amount", "events[0].cash_movements[0].amount", "Zahlbetrag", "Ausgewiesene Ausschüttung", "DECIMAL", requirement="REQUIRED", editor="AMOUNT", order=30),
    FieldDefinition("payment.currency", "events[0].cash_movements[0].currency", "Währung", "Zahlungswährung", requirement="REQUIRED", order=40),
    FieldDefinition("payment.status", "events[0].cash_movements[0].status", "Cashflowstatus", "ACTUAL oder EXPECTED", requirement="REQUIRED", order=50),
    FieldDefinition("payment.taxes", "events[0].tax_events", "Steuern", "Nur ausgewiesene Steuerinformationen", "LIST", requirement="OPTIONAL", order=60),
)

DEFAULT_FIELDS = TECHNICAL_FIELDS


def fields_for_document(parser_id: str, document_type: str):
    value = f"{parser_id} {document_type}".casefold()
    if document_type == "*" and "comdirect" in parser_id.casefold(): return TRADE_FIELDS + TECHNICAL_FIELDS
    if "mifid" in value or "kosteninformation" in value: return MIFID_FIELDS + TECHNICAL_FIELDS
    if "finanzreport" in value or "kontoauszug" in value or "bank of scotland" in value: return ACCOUNT_FIELDS + TECHNICAL_FIELDS
    if "depotauszug" in value: return DEPOT_FIELDS + TECHNICAL_FIELDS
    if "umsatzabrechnung" in value: return ACCOUNT_FIELDS + DEPOT_FIELDS + TECHNICAL_FIELDS
    if "vorabpauschale" in value or "dividendensteuer" in value: return TAX_FIELDS + TECHNICAL_FIELDS
    if any(item in value for item in ("dividende", "ertragsgutschrift", "ausschüttung", "ausschuettung")): return DIVIDEND_FIELDS + TECHNICAL_FIELDS
    if any(item in value for item in ("wertpapierkauf", "wertpapierverkauf", " kauf", " verkauf", "einlösung", "einloesung")): return TRADE_FIELDS + TECHNICAL_FIELDS
    return TECHNICAL_FIELDS


class FieldCatalog:
    SCHEMA_VERSION = 1

    def __init__(self, bank: str, parser_id: str, document_type: str, layout: str,
                 version: int, fields: tuple[FieldDefinition, ...], path: Path | None = None):
        self.bank, self.parser_id, self.document_type, self.layout = bank, parser_id, document_type, layout
        self.version, self.fields, self.path = version, fields, path

    def field(self, path_or_id: str) -> FieldDefinition | None:
        return next((item for item in self.fields if item.path == path_or_id or item.field_id == path_or_id), None)

    def visible_fields(self):
        return tuple(sorted((item for item in self.fields if item.visible), key=lambda item: item.order))

    def save(self, path: str | Path) -> Path:
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": self.SCHEMA_VERSION, "catalog_version": self.version, "bank": self.bank,
                   "parser_id": self.parser_id, "document_type": self.document_type, "layout": self.layout,
                   "fields": [asdict(item) for item in self.fields]}
        target.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path):
        source = Path(path); payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported field catalog schema")
        fields = tuple(FieldDefinition(**{**item, "patterns": tuple(item.get("patterns", ())),
                                           "normalizers": tuple(item.get("normalizers", ("TEXT",))),
                                           "available_rules": tuple(item.get("available_rules", ("STANDARD", "EXTENDED")))})
                       for item in payload.get("fields", ()))
        paths = [item.path for item in fields]
        if len(paths) != len(set(paths)) or any(not item.field_id or not item.path for item in fields):
            raise ValueError("field catalog contains duplicate or empty paths")
        return cls(payload["bank"], payload["parser_id"], payload["document_type"], payload.get("layout", "*"),
                   int(payload["catalog_version"]), fields, source)


class CatalogStore:
    def __init__(self, root: str | Path):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _stem(bank, parser_id, document_type, layout):
        clean = lambda value: re.sub(r"[^a-zA-Z0-9_.-]", "_", value or "all").strip("._") or "all"
        return ".".join(map(clean, (bank, parser_id, document_type, layout)))

    def catalog(self, bank="comdirect", parser_id="user.comdirect-ertraege", document_type="*", layout="*"):
        candidates = sorted(self.root.glob(f"{bank}.*.yaml"))
        compatible = []
        for path in candidates:
            catalog = FieldCatalog.load(path)
            if catalog.parser_id in {parser_id, "*"} and catalog.document_type in {document_type, "*"} and catalog.layout in {layout, "*"}:
                compatible.append(catalog)
        if compatible:
            return max(compatible, key=lambda item: (sum((item.parser_id == parser_id,
                                                           item.document_type == document_type,
                                                           item.layout == layout)), item.version))
        catalog = FieldCatalog(bank, parser_id, document_type, layout, 1, fields_for_document(parser_id, document_type))
        catalog.path = catalog.save(self.root / f"{self._stem(bank, parser_id, document_type, layout)}.v1.yaml")
        return catalog

    def add_optional_field(self, catalog: FieldCatalog, field_id: str, label: str, data_type="TEXT"):
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", field_id).strip("._")
        if not safe_id:
            raise ValueError("field id is empty")
        path = f"attributes.user_fields.{safe_id}"
        if catalog.field(path) or catalog.field(safe_id):
            raise ValueError("field already exists")
        definition = FieldDefinition(safe_id, path, label or safe_id, "Benutzerdefiniertes optionales Anzeigefeld",
                                     data_type, requirement="OPTIONAL", order=800)
        updated = FieldCatalog(catalog.bank, catalog.parser_id, catalog.document_type, catalog.layout,
                               catalog.version + 1, catalog.fields + (definition,))
        updated.path = updated.save(self.root / f"{self._stem(catalog.bank, catalog.parser_id, catalog.document_type, catalog.layout)}.v{updated.version}.yaml")
        return updated, definition
