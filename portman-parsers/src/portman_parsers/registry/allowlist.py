"""Explicit parser allowlist; variants are registered without filesystem discovery."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HandlerMetadata:
    handler_id: str
    document_type: str
    implemented: bool = False


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    plugin_id: str
    group: str
    version: str
    handlers: tuple[HandlerMetadata, ...]


def _handlers(*items: tuple[str, str]) -> tuple[HandlerMetadata, ...]:
    return tuple(HandlerMetadata(*item) for item in items)


APPROVED_PLUGINS: tuple[PluginMetadata, ...] = (
    PluginMetadata("user.comdirect-ertraege", "comdirect", "2.0", (
        HandlerMetadata("dividendengutschrift", "comdirect Dividendengutschrift", True),
        HandlerMetadata("ertragsgutschrift", "comdirect Ertragsgutschrift", True),
        HandlerMetadata("einloesung", "comdirect Einlösung", True),
        HandlerMetadata("kosteninformation_mifid_ii", "comdirect MiFID-II-Kosteninformation", True),
        HandlerMetadata("investment_ausschuettung", "comdirect Investment-Ausschüttung", True),
        HandlerMetadata("dividende_steuer_inland", "comdirect inländische Dividendensteuer", True),
        HandlerMetadata("vorabpauschale", "comdirect Vorabpauschale", True),
        HandlerMetadata("wertpapierkauf", "comdirect Wertpapierkauf", True),
        HandlerMetadata("wertpapierverkauf", "comdirect Wertpapierverkauf", True),
    )),
    PluginMetadata("comdirect.finanzreport", "comdirect", "3.0", (
        HandlerMetadata("finanzreport", "comdirect Finanzreport", True),
    )),
    PluginMetadata("portfolio-performance.comdirect", "comdirect", "pp-c08d5053", (
        HandlerMetadata("dividendengutschrift", "PP comdirect Dividendengutschrift", True),
        HandlerMetadata("ertragsgutschrift", "PP comdirect Ertragsgutschrift", True),
        HandlerMetadata("einloesung", "PP comdirect Einlösung", True),
        HandlerMetadata("investment_ausschuettung", "PP comdirect Investment-Ausschüttung", True),
        HandlerMetadata("dividende_steuer_inland", "PP comdirect Dividendensteuer", True),
        HandlerMetadata("vorabpauschale", "PP comdirect Vorabpauschale", True),
        HandlerMetadata("wertpapierkauf", "PP comdirect Wertpapierkauf", True),
        HandlerMetadata("wertpapierverkauf", "PP comdirect Wertpapierverkauf", True),
        HandlerMetadata("finanzreport", "PP comdirect Finanzreport", True),
    )),
    PluginMetadata("baader.pdf", "Baader", "1.0", _handlers(
        ("quartalsaufstellung", "Baader Quartalsaufstellung"),
        ("jahresdepotauszug", "Baader Jahresdepotauszug"),
        ("dividende", "Baader Dividendenabrechnung"),
        ("vorabpauschale", "Baader Vorabpauschale"),
        ("depotuebertrag", "Baader Depotein-/auslieferung"),
        ("wertpapierabrechnung", "Baader Wertpapierabrechnung"),
    )),
    PluginMetadata("user.ing-wertpapiere", "ING", "1.0", _handlers(
        ("dividendengutschrift", "ING Dividendengutschrift"),
        ("kauf", "ING Wertpapierkauf"),
        ("verkauf", "ING Wertpapierverkauf"),
        ("vorabpauschale", "ING Vorabpauschale"),
        ("steuerverrechnung", "ING Steuerverrechnung"),
        ("jahresdepotauszug", "ING Jahresdepotauszug"),
    )),
    PluginMetadata("user.deka-quartalsbericht", "Deka", "1.0", _handlers(
        ("quartalsbericht", "Deka Quartalsbericht/Jahresdepotauszug"),
    )),
    PluginMetadata("fnz.finvesto", "FNZ / Finvesto", "2.0", (
        HandlerMetadata("umsatzabrechnung", "FNZ Umsatzabrechnung", True),
        HandlerMetadata("depotauszug", "FNZ Depotauszug", True),
    )),
    PluginMetadata("renault.kontoauszug", "Renault", "2.0", _handlers(
        ("kontoauszug", "Renault Kontoauszug"),
        ("zinsmitteilung", "Renault Zinsmitteilung"),
        ("steuerbescheinigung", "Renault Jahressteuerbescheinigung"),
        ("freistellungsauftrag", "Renault Freistellungsauftrag"),
        ("umsatzuebersicht", "Renault Umsatzübersicht"),
        ("archiv", "Renault Archivdokument"),
    )),
    PluginMetadata("user.bank-of-scotland-kontoauszug", "Bank of Scotland", "1.0", (
        HandlerMetadata("kontoauszug", "Bank of Scotland Kontoauszug", True),
    )),
    PluginMetadata("generic.kontoauszug", "Generischer Dokument-Fallback", "1.0", _handlers(
        ("generic", "Generisches prüfpflichtiges Dokument"),
    )),
)

BLOCKED_MODULES = frozenset({"pbb_direkt", "baader_krypto"})


def validate_allowlist() -> None:
    ids = [plugin.plugin_id for plugin in APPROVED_PLUGINS]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate plugin id in allowlist")
    if sum(len(plugin.handlers) for plugin in APPROVED_PLUGINS) != 42:
        raise RuntimeError("allowlist must contain exactly 42 handlers")
    if {plugin.group for plugin in APPROVED_PLUGINS} != {
        "comdirect", "Baader", "ING", "Deka", "FNZ / Finvesto", "Renault",
        "Bank of Scotland", "Generischer Dokument-Fallback",
    }:
        raise RuntimeError("Phase-3 allowlist must contain exactly the eight approved groups")


validate_allowlist()

