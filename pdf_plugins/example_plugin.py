"""Beispiel-Plugin für externe Anbieter.

Dieses Plugin demonstriert die Python-Schnittstelle für PDF-Import-Plugin.
Es kann als Vorlage für eigene Bank-Plugins verwendet werden.

Installation:
  1. Diese Datei im Ordner pdf_plugins/ ablegen
  2. Im Hauptfenster unter "Extras → PDF-Import-Plugins" prüfen
"""
from portfolio_v5.pdf_plugins import Detection, PdfDocument, ParseContext
from portfolio_v5.models import ImportBatch


class ExamplePlugin:
    """Einfaches Beispiel-Plugin für eine fiktive Bank."""

    plugin_id = "example.bank.python"
    bank_name = "Example Bank"
    version = "1.0.0"

    def detect(self, document: PdfDocument) -> list[Detection]:
        """Prüft, ob dieses Plugin das Dokument verarbeiten kann."""
        if "Example Bank" not in document.text:
            return []
        detections = []
        if "Kontoauszug" in document.text:
            detections.append(Detection(
                confidence=0.90,
                document_type="Example Bank Kontoauszug",
                handler_id="kontoauszug",
                reason="Bankenname und Kontoauszug erkannt"
            ))
        if "Depotübersicht" in document.text:
            detections.append(Detection(
                confidence=0.85,
                document_type="Example Bank Depotstand",
                handler_id="depotstand",
                reason="Bankenname und Depotübersicht erkannt"
            ))
        return detections

    def parse(self, document: PdfDocument, detection: Detection, context: ParseContext) -> ImportBatch:
        """Parst das Dokument und gibt einen ImportBatch zurück."""
        batch = context.batch
        batch.document_type = detection.document_type
        batch.account_names = [self.bank_name]
        # Parsing-Logik hier implementieren
        return batch


plugin = ExamplePlugin()
