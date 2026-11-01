"""Versioned, reusable German descriptions for public parser DTO fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import tempfile
import warnings
from pathlib import Path
import re
from typing import Any

from .field_catalog import FieldCatalog, FieldDefinition, normalize_field_path


DESCRIPTION_SCHEMA_VERSION = 1
@dataclass(frozen=True)
class DescriptionEntry:
    normalized_path: str
    description: str
    source: str
    schema_version: int = DESCRIPTION_SCHEMA_VERSION
    status: str = "AUTO_DERIVED"


_KNOWN: dict[str, str] = {
    "bank_name": "Name der kontoführenden Bank",
    "account_name": "Bezeichnung des Bankkontos",
    "account_id": "Eindeutige Kennung des Bankkontos",
    "account_number": "Kontonummer des Bankkontos",
    "iban": "Internationale Bankkontonummer",
    "bic": "Internationale Kennung des kontoführenden Instituts",
    "currency": "Währung des zugehörigen Kontos oder Betrags",
    "isin": "Internationale Wertpapierkennnummer",
    "wkn": "Wertpapierkennnummer",
    "security_name": "Bezeichnung des Wertpapiers",
    "quantity": "Anzahl der Wertpapierstücke oder Anteile",
    "gross_amount": "Bruttobetrag vor den ausgewiesenen Abzügen",
    "settlement_amount": "Settlementbetrag nach den ausgewiesenen Zu- und Abzügen",
    "net_amount": "Nettobetrag nach den ausgewiesenen Abzügen",
    "value_date": "Datum der Wertstellung",
    "trade_date": "Datum des Wertpapiergeschäfts",
    "execution_date": "Datum der Ausführung des Wertpapiergeschäfts",
    "price": "Ausgewiesener Kurs des Wertpapiers",
    "market_value": "Ausgewiesener Markt- oder Kurswert",
    "amount": "Ausgewiesener Geldbetrag",
    "tax_amount": "Ausgewiesener Steuerbetrag",
    "fee_amount": "Ausgewiesener Gebührenbetrag",
    "fee_date": "Datum der Gebührenposition",
    "venue": "Handelsplatz beziehungsweise Börsenplatz",
    "security_id": "Kennung des Wertpapiers",
    "depot_id": "Eindeutige Kennung des Depots",
    "depot_number": "Depotnummer",
    "account_ref": "Referenz auf das zugehörige Konto",
    "custom_reference": "Zusätzlicher Referenzwert des zugehörigen Objekts",
    "result_id": "Eindeutige Kennung dieses Parserergebnisses",
    "document_id": "Eindeutige Kennung des ausgewerteten Dokuments",
    "plugin_id": "Eindeutige Kennung des verwendeten Parser-Plugins",
    "plugin_version": "Version des verwendeten Parser-Plugins",
    "handler_id": "Kennung des Parsers für den erkannten Dokumenttyp",
    "schema_version": "Version des ausgegebenen DTO-Datenschemas",
    "event_id": "Eindeutige Kennung des wirtschaftlichen Vorgangs",
    "event_date": "Datum des wirtschaftlichen Vorgangs",
    "kind": "Fachliche Art des zugehörigen Vorgangs oder Bestandteils",
    "movement_id": "Eindeutige Kennung der Geld- oder Wertpapierbewegung",
    "movement_type": "Fachliche Art der Kontobewegung",
    "side": "Richtung des Wertpapiergeschäfts: Kauf, Verkauf oder Einlösung",
    "trade_id": "Eindeutige Kennung des Wertpapiergeschäfts",
    "price_currency": "Währung des ausgewiesenen Wertpapierkurses",
    "settlement_currency": "Währung des Abrechnungsbetrags",
    "exchange_rate": "Ausgewiesener Wechselkurs der Abrechnung",
    "status": "Status des zugehörigen Vorgangs",
    "tax_event_id": "Eindeutige Kennung des Steuervorgangs",
    "tax_year": "Steuerjahr, auf das sich die Angabe bezieht",
    "taxable_basis": "Ausgewiesene steuerliche Bemessungsgrundlage",
    "assessment_basis": "Bemessungsgrundlage der Vorabpauschale",
    "advance_before_partial_exemption": "Vorabpauschale vor Anwendung der Teilfreistellung",
    "taxable_amount": "Nach Teilfreistellung steuerpflichtiger Betrag",
    "stated_tax_liability": "Im Dokument ausgewiesene Steuerschuld",
    "actually_withheld_tax": "Tatsächlich einbehaltener Steuerbetrag",
    "distributions": "Im Berechnungszeitraum berücksichtigte Ausschüttungen",
    "start_value": "Wert der Fondsanteile zu Beginn des Berechnungszeitraums",
    "end_value": "Wert der Fondsanteile am Ende des Berechnungszeitraums",
    "partial_exemption_rate": "Angewendeter Teilfreistellungssatz",
    "exemption_order_used": "Verbrauchter Betrag des Freistellungsauftrags",
    "loss_offset_used": "Verrechneter Betrag aus dem Verlusttopf",
    "acquisition_date": "Anschaffungsdatum der betroffenen Wertpapierposition",
    "accrual_date": "Steuerlicher Entstehungs- oder Zuflusszeitpunkt",
    "booking_date": "Datum der Buchung auf dem Konto",
    "approval_status": "Freigabestatus der steuerlichen Berechnung",
    "component": "Einzelner Bestandteil des zugehörigen Vorgangs",
    "category": "Gebührenkategorie",
    "subcategory": "Unterkategorie der Gebühr",
    "effect": "Wirtschaftliche Wirkung der Gebühr",
    "fee_id": "Eindeutige Kennung der Gebührenposition",
    "cost_event_id": "Eindeutige Kennung der Kosteninformation",
    "information_type": "Art der MiFID-Kosteninformation",
    "informational": "Kennzeichen, dass die Angabe nur informatorisch und kein Cashflow ist",
    "external_reference": "Vom Dokument übernommene externe Referenz",
    "reversal_of_event_id": "Kennung des wirtschaftlichen Vorgangs, der storniert wird",
    "reverses_fee_id": "Kennung der Gebührenposition, die storniert wird",
    "linked_cash_movement_id": "Kennung der zugehörigen Geldbewegung",
    "linked_security_movement_id": "Kennung der zugehörigen Wertpapierbewegung",
    "cash_movement_id": "Kennung der zugeordneten Geldbewegung",
    "transaction_id": "Kennung der zugeordneten Transaktion",
    "transfer_id": "Gemeinsame Kennung zusammengehöriger Umbuchungen",
    "counterpart_movement_id": "Kennung der Gegenbuchung einer Umbuchung",
    "bank_id": "Kennung der Bank im Parser-Datenmodell",
    "holder_name": "Name des Konto- oder Depotinhabers",
    "account_type": "Art des Bankkontos",
    "functions": "Fachliche Funktionen des Bankkontos",
    "depot_name": "Bezeichnung des Wertpapierdepots",
    "base_currency": "Basiswährung des Depots",
    "depot_type": "Art des Wertpapierdepots",
    "snapshot_id": "Eindeutige Kennung des Bestandsstichtags",
    "position_id": "Eindeutige Kennung der Depotposition",
    "as_of": "Stichtag, für den der Bestand oder Saldo gilt",
    "total_value": "Ausgewiesener Gesamtwert des Depots zum Stichtag",
    "price_date": "Stichtag des ausgewiesenen Wertpapierkurses",
    "balance_id": "Eindeutige Kennung des Kontosaldos",
    "balance_type": "Art des ausgewiesenen Kontosaldos",
    "link_id": "Eindeutige Kennung der Konto-Depot-Zuordnung",
    "role": "Funktion des Kontos für das zugeordnete Depot",
    "valid_from": "Beginn der Gültigkeit der Konto-Depot-Zuordnung",
    "valid_until": "Ende der Gültigkeit der Konto-Depot-Zuordnung",
    "is_default": "Kennzeichen für die standardmäßig verwendete Konto-Depot-Zuordnung",
    "evidence_id": "Eindeutige Kennung der PDF-Fundstelle",
    "evidence_ids": "Kennungen der PDF-Fundstellen, die diesen Wert belegen",
    "page_number": "Seitenzahl der PDF-Fundstelle",
    "field": "Feldpfad, den diese PDF-Fundstelle belegt",
    "excerpt": "Textausschnitt aus dem PDF als Beleg",
    "source_ref": "Technische Referenz auf die Quelle der Fundstelle",
    "document_hash": "Prüfsumme des ausgewerteten Dokuments",
    "parser_id": "Kennung des Parsers, der die Fundstelle erzeugt hat",
    "parser_version": "Version des Parsers, der die Fundstelle erzeugt hat",
    "review_status": "Prüfstatus des extrahierten Werts oder der Fundstelle",
    "source": "Herkunft des Feldwerts: PDF, manuell, abgeleitet oder nicht angegeben",
    "issue_id": "Eindeutige Kennung des Prüfhinweises",
    "code": "Maschinenlesbarer Code des Prüfhinweises",
    "severity": "Schweregrad des Prüfhinweises",
    "message": "Verständliche Meldung des Prüfhinweises",
    "nature": "Fachliche Kategorie des Prüfhinweises",
    "attributes": "Vom Parser ausgegebene zusätzliche Schlüssel-Wert-Angaben",
    "events": "Vom Dokument erkannte wirtschaftliche Vorgänge",
    "cash_movements": "Geldbewegungen des wirtschaftlichen Vorgangs",
    "security_movements": "Bestandsveränderungen von Wertpapieren des wirtschaftlichen Vorgangs",
    "trades": "Wertpapiergeschäfte des wirtschaftlichen Vorgangs",
    "tax_events": "Steuerliche Angaben des wirtschaftlichen Vorgangs",
    "fee_events": "Gebührenpositionen des wirtschaftlichen Vorgangs",
    "cost_events": "Kosteninformationen des wirtschaftlichen Vorgangs",
    "components": "Einzelne Steuerbestandteile des Steuervorgangs",
    "allocations": "Zuordnungen einer Gebühr zu anderen Vorgängen",
    "target_type": "Art des Objekts, dem die Gebühr zugeordnet ist",
    "target_id": "Kennung des Objekts, dem die Gebühr zugeordnet ist",
    "fee_ids": "Kennungen der Gebührenpositionen, auf die sich die Kosteninformation bezieht",
    "snapshots": "Aus dem Dokument erkannte Bestandsaufnahmen im älteren Snapshot-DTO",
    "depots": "Aus dem Dokument erkannte Wertpapierdepots",
    "accounts": "Aus dem Dokument erkannte Bankkonten",
    "depot_snapshots": "Depotbestände zu einem bestimmten Stichtag",
    "account_balances": "Kontosalden zu einem bestimmten Stichtag",
    "depot_account_links": "Explizite Zuordnungen zwischen Depots und Bankkonten",
    "tax_calculations": "Berechnete und prüfpflichtige Ergebnisse zur Vorabpauschale",
    "tax_carryforwards": "Fortgeschriebene bereits besteuerte Vorabpauschalen",
    "positions": "Wertpapierpositionen innerhalb der Bestandsaufnahme",
    "expected_components": "Nach dem Steuermodell erwartete Steuerbestandteile",
    "differences": "Benannte Abweichungen zwischen ausgewiesenen und berechneten Steuerwerten",
    "base_yield": "Basisertrag der Vorabpauschalenberechnung",
    "appreciation_cap": "Begrenzung des Basisertrags auf die tatsächliche Wertsteigerung",
    "assessed_tax_liability": "Nach dem Steuermodell berechnete Steuerschuld",
    "pro_rata_factor": "Zeitanteil für nicht während des ganzen Jahres gehaltene Anteile",
    "rule_source_reference": "Quellenangabe für die verwendete steuerliche Rechenregel",
    "carryforward_id": "Eindeutige Kennung der steuerlichen Vorabpauschalen-Fortschreibung",
    "taxed_advance_amount": "Bereits besteuerter und für spätere Veräußerungen fortgeschriebener Vorabpauschalenbetrag",
    "base_rate": "Gesetzlicher Basiszinssatz für das betreffende Steuerjahr",
    "rate": "Wert des gesetzlichen Basiszinssatzes",
    "base_yield_factor": "Gesetzlicher Faktor zur Ermittlung des Basisertrags",
    "capital_gains_tax_rate": "Verwendeter Kapitalertragsteuersatz",
    "solidarity_rate": "Verwendeter Solidaritätszuschlagssatz",
    "church_tax_rate": "Verwendeter Kirchensteuersatz, sofern bekannt",
    "source_reference": "Nachvollziehbare Quellenangabe für den gesetzlichen Wert",
    "published_on": "Datum der Veröffentlichung des gesetzlichen Werts",
    "jurisdiction": "Staatlicher Geltungsbereich der steuerlichen Regel",
    "value": "Eigentlicher Nutzwert eines FieldValue-DTOs",
    "evidence": "PDF-Fundstellen, mit denen Parserwerte belegt werden",
    "issues": "Bei Erkennung oder Validierung erzeugte Prüfhinweise",
    "pages": "Extrahierte Seiten des PDF-Dokuments",
    "number": "Seitennummer innerhalb des PDF-Dokuments",
    "text": "Aus der PDF-Seite extrahierter Text",
    "filename": "Dateiname des ausgewerteten PDF-Dokuments",
    "source_hash": "Prüfsumme der ursprünglichen Dokumentquelle",
    "metadata": "Technische Metadaten des PDF-Dokuments",
    "extraction_method": "Verfahren, mit dem der Seitentext gewonnen wurde",
    "confidence": "Vom Extraktionsverfahren angegebene Sicherheit zwischen 0 und 1",
    "document_type": "Vom Parser erkannter fachlicher Dokumenttyp",
    "reason": "Begründung für die Dokumenterkennung",
}


def description_lookup_path(path: str) -> str:
    """Return the stable, index-independent DTO path used by the catalog."""
    # FieldValue is a transport wrapper, not a separate business field.  Keep
    # the caller's original path for display, but use the unwrapped path for
    # description lookup.
    return normalize_field_path(path)


def _context_description(path: str, leaf: str) -> str | None:
    if leaf == "value" and len(path.split(".")) > 1:
        parent = path.rsplit(".", 1)[0]
        return _context_description(parent, parent.rsplit(".", 1)[-1]) or _KNOWN.get(parent.rsplit(".", 1)[-1])
    if leaf == "quantity":
        if ".positions[]" in path or "depot_snapshots[]" in path:
            return "Anzahl der im Depot gehaltenen Wertpapierstücke oder Anteile"
        if ".trades[]" in path or ".security_movements[]" in path:
            return "Anzahl der gehandelten Wertpapierstücke oder Anteile"
    if leaf == "currency":
        if ".cash_movements[]" in path:
            return "Währung des Geldbetrags"
        if ".trades[]" in path:
            return "Währung des Wertpapierbetrags"
    if leaf == "amount":
        if ".fee_events[]" in path:
            return "Ausgewiesener Gebührenbetrag"
        if ".tax_events[]" in path or ".components[]" in path:
            return "Ausgewiesener Steuerbetrag"
        if ".cash_movements[]" in path:
            return "Ausgewiesener Betrag der Kontobewegung"
        if "account_balances[]" in path:
            return "Ausgewiesener Kontosaldo zum Stichtag"
        if ".cost_events[]" in path:
            return "Ausgewiesener Betrag der Kosteninformation"
    if leaf == "currency":
        if ".fee_events[]" in path:
            return "Währung des Gebührenbetrags"
        if ".tax_events[]" in path or ".components[]" in path:
            return "Währung des Steuerbetrags"
        if "account_balances[]" in path:
            return "Währung des Kontosaldos"
        if "depot_snapshots[]" in path:
            return "Währung der Depotbewertung"
    if leaf == "security_id":
        if ".positions[]" in path:
            return "Kennung des Wertpapiers dieser Depotposition"
        if ".security_movements[]" in path:
            return "Kennung des Wertpapiers dieser Bestandsbewegung"
    if leaf == "custom_reference" and path.startswith("accounts[]"):
        return "Zusätzlicher Referenzwert des Bankkontos"
    return None


def _neutral_description(path: str) -> str:
    parts = [part for part in description_lookup_path(path).split(".") if part]
    leaf = parts[-1] if parts else "Feld"
    contextual = _context_description(".".join(parts), leaf)
    if contextual:
        return contextual
    if leaf in _KNOWN:
        return _KNOWN[leaf]
    if "attributes" in parts:
        return f"Parser-spezifische Zusatzangabe mit dem Schlüssel „{leaf}“; die fachliche Bedeutung wird durch den Schlüssel festgelegt"
    return f"DTO-Feld „{leaf}“; im Quellmodell ist keine weitergehende fachliche Bedeutung definiert"


class DescriptionCatalog:
    def __init__(self, entries: tuple[DescriptionEntry, ...] = (), path: Path | None = None):
        self.path = path
        self._entries = {entry.normalized_path: entry for entry in entries}

    @classmethod
    def load(cls, path: str | Path):
        source = Path(path)
        if not source.exists():
            return cls(path=source)
        raw = source.read_text(encoding="utf-8")
        if not raw.strip():
            # An interrupted/empty store is safe to rebuild from field definitions.
            return cls(path=source)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Preserve malformed user data for investigation; never overwrite it.
            warnings.warn(f"Invalid description catalog preserved at {source}", RuntimeWarning)
            return cls()
        if not isinstance(payload, dict):
            warnings.warn(f"Invalid description catalog structure preserved at {source}", RuntimeWarning)
            return cls()
        if int(payload.get("schema_version", 0)) != DESCRIPTION_SCHEMA_VERSION:
            raise ValueError("unsupported description catalog schema")
        entries = tuple(DescriptionEntry(**item) for item in payload.get("entries", ()))
        return cls(entries, source)

    def save(self) -> Path:
        if self.path is None:
            raise ValueError("description catalog has no path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"schema_version": DESCRIPTION_SCHEMA_VERSION,
                              "entries": [asdict(item) for item in sorted(self._entries.values(), key=lambda x: x.normalized_path)]},
                             ensure_ascii=False, indent=2)
        # Never expose a truncated JSON file to Qt callbacks reading the store.
        fd, tmp_name = tempfile.mkstemp(prefix=".field-descriptions-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return self.path

    def get(self, path: str) -> DescriptionEntry | None:
        return self._entries.get(description_lookup_path(path))

    def put(self, entry: DescriptionEntry) -> DescriptionEntry:
        existing = self._entries.get(entry.normalized_path)
        if existing and existing.status == "VERIFIED":
            return existing
        self._entries[entry.normalized_path] = entry
        return entry

    def resolve(self, path: str, definition: FieldDefinition | None = None) -> DescriptionEntry:
        normalized = description_lookup_path(path)
        existing = self.get(path)
        if existing:
            return existing
        if definition and definition.description.strip():
            entry = DescriptionEntry(normalized, definition.description.strip(), "field_catalog", status="VERIFIED")
        else:
            entry = DescriptionEntry(normalized, _neutral_description(path), "dto_context_derived")
        return self.put(entry)


def catalog_for_field_catalog(catalog: FieldCatalog | None) -> DescriptionCatalog:
    path = catalog.path.parent / "field-descriptions.v1.json" if catalog and catalog.path else None
    return DescriptionCatalog.load(path) if path else DescriptionCatalog()


def resolve_description(path: str, catalog: FieldCatalog | None = None,
                        description_catalog: DescriptionCatalog | None = None) -> DescriptionEntry:
    definition = None
    if catalog:
        definition = catalog.field_for_description(path)
    store = description_catalog or catalog_for_field_catalog(catalog)
    existing = store.get(path)
    if existing is not None:
        return existing
    entry = store.resolve(path, definition)
    if store.path:
        try:
            store.save()
        except PermissionError:
            # A concurrent Qt callback or Windows file scanner may hold the
            # destination; the description remains available in memory.
            warnings.warn(f"Description catalog temporarily locked: {store.path}", RuntimeWarning)
    return entry
