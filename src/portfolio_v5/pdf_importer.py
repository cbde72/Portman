"""Read statements, extract locally with OCR as needed, and prepare a review batch."""
import hashlib
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pypdf import PdfReader

from .models import ImportBatch, transaction_validation, valid_isin
from pdf_plugins._generic_document import analyse_pages as analyse_pages  # re-exported for tests
from pdf_plugins._generic_document import parse_generic_document


def _validate_plugin_batch(batch, document):
    ids = [tx.external_id for tx in batch.transactions]
    if len(ids) != len(set(ids)): raise ValueError('Plugin erzeugte mehrfach verwendete Buchungskennungen.')
    for tx in batch.transactions:
        if not tx.account or not tx.external_id or not tx.date or not tx.currency or tx.amount is None:
            raise ValueError('Plugin erzeugte eine unvollständige Buchung.')
        try:
            date.fromisoformat(tx.date)
            amount = Decimal(tx.amount)
            if not amount.is_finite(): raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f'Plugin erzeugte eine Buchung mit ungültigem Datum oder Betrag: {tx.external_id}.') from None
        hard_problems, advisory = transaction_validation(tx)
        if hard_problems:
            raise ValueError(f'Buchung {tx.external_id}: ' + '; '.join(hard_problems))
        batch.warnings.extend(f'Buchung {tx.external_id}: {problem}' for problem in advisory)
    for snapshot in batch.snapshots:
        if not snapshot.account or not snapshot.as_of:
            raise ValueError('Plugin erzeugte einen Depotstand ohne Depot oder Stichtag.')
        try:
            date.fromisoformat(snapshot.as_of)
        except (TypeError, ValueError):
            raise ValueError(f'Plugin erzeugte einen Depotstand mit ungültigem Stichtag: {snapshot.as_of!r}.') from None
        for position in snapshot.positions:
            if position.isin and not valid_isin(position.isin):
                batch.warnings.append(
                    f'{snapshot.sheet}: ungültige ISIN {position.isin!r} bei {position.name}; Originalwert beibehalten.')
            for field in ('quantity', 'cost', 'value', 'price'):
                value = getattr(position, field, None)
                if value is not None:
                    try:
                        parsed = Decimal(value)
                        if not parsed.is_finite(): raise InvalidOperation
                    except (InvalidOperation, TypeError, ValueError):
                        raise ValueError(f'{snapshot.sheet}: {position.name}: {field} ist keine endliche Zahl.') from None
    if batch.file_hash != document.file_hash: raise ValueError('Plugin darf den PDF-Dateihash nicht verändern.')


def parse_pdf(path, *, allow_ocr=True, preferred_plugin=None, preferred_handler=None, profile_dirs=(),
              document_tags=None, plugin_catalog=None):
    path = Path(path).resolve()
    batch = ImportBatch(str(path), '', source_sheet='PDF')
    try:
        content = path.read_bytes()
        batch.file_hash = hashlib.sha256(content).hexdigest()
        # Optional native accelerator is implemented in the external plugin
        # directory; the core only accepts its validated ImportBatch result.
        from pdf_plugins._comdirect_fast import try_fast_finanzreport
        fast = try_fast_finanzreport(path, content)
        if fast is not None:
            fast.plugin_id, fast.plugin_version, fast.plugin_handler = 'comdirect.finanzreport', '2.0', 'finanzreport'
            fast.detection_confidence = 1.0
            fast.warnings.append('PDF-Plugin: comdirect · Finanzreport · Erkennung 100 %')
            return fast
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('PDF ist passwortgeschützt. Bitte zuerst eine entsperrte Kopie erstellen.')
        pages, ocr_pages = [], {}
        fallback_pages = set()
        from .pdf_text import extract_page_text
        from .pdf_ocr import ocr_page
        for index, page in enumerate(reader.pages):
            extracted, needs_layout_review = extract_page_text(page)
            if needs_layout_review:
                fallback_pages.add(index + 1)
                batch.warnings.append(f'Seite {index + 1}: Gedrehter Text oder Layoutproblem. Alternative Textextraktion verwendet; Vollständigkeit und Tabellenspalten am Original prüfen.')
            # Image-backed pages with little useful text also include scans with
            # a selectable letterhead. Do not concatenate OCR and native text.
            visible = len(re.sub(r'\s', '', extracted))
            # pypdf reports rotated content and uninterpretable embedded fonts
            # through the reviewed fallback flag. Native text can look plausible
            # while still omitting complete booking rows, so verify that page by OCR.
            needs_ocr = needs_layout_review or visible == 0 or ('\ufffd' in extracted and extracted.count('\ufffd') > visible * .05)
            if not needs_ocr and visible < 300:
                needs_ocr = bool(page.images)
                # The short, fully textual account appendix also contains a bank
                # logo. Its image is not a scanned statement and needs no OCR.
                compact = ' '.join(extracted.split())
                if (re.search(r'Finanzreport\s+Nr\.', compact, re.I)
                        and 'Übersicht Ihrer Kontodaten' in compact
                        and re.search(r'DE(?: ?\d){20}', compact)):
                    needs_ocr = False
            if needs_ocr and not allow_ocr:
                batch.warnings.append(f'Seite {index + 1}: Textergänzung nur aus eingebettetem Text, ohne OCR.')
            if needs_ocr and allow_ocr:
                try:
                    recognized, confidence = ocr_page(path, index)
                    if recognized.strip():
                        extracted = recognized
                        ocr_pages[index + 1] = confidence
                        batch.warnings.append(f'Seite {index + 1}: OCR verwendet; Buchungen bitte am Original prüfen und einzeln bestätigen.')
                    else:
                        batch.warnings.append(f'Seite {index + 1}: OCR hat keinen Text erkannt; nur Dokumentablage möglich.')
                except Exception as error:
                    batch.warnings.append(f'Seite {index + 1}: OCR fehlgeschlagen ({error}); vorhandener Text bleibt verfügbar.')
            pages.append(extracted)
        from .pdf_plugins import PdfDocument, PdfPage, ParseContext, discover_plugins, select_plugin
        document = PdfDocument(path, content, batch.file_hash, tuple(
            PdfPage(number, text, number in ocr_pages, ocr_pages.get(number))
            for number, text in enumerate(pages, 1)))
        plugins, plugin_errors = (discover_plugins(profile_dirs) if plugin_catalog is None
                                  else plugin_catalog)
        selected = None
        if preferred_plugin:
            plugin = next((item for item in plugins if item.plugin_id == preferred_plugin), None)
            if plugin is None: raise ValueError('Gewähltes PDF-Plugin ist nicht installiert: ' + preferred_plugin)
            detections = plugin.detect(document)
            matches = [item for item in detections if not preferred_handler or item.handler_id == preferred_handler]
            matches.sort(key=lambda item: item.confidence, reverse=True)
            if len(matches) > 1 and not preferred_handler \
                    and matches[0].confidence - matches[1].confidence < .10 \
                    and matches[0].handler_id != matches[1].handler_id:
                raise ValueError('Gewähltes PDF-Plugin erkennt mehrere Dokumenttypen nahezu gleich sicher; Handler ausdrücklich wählen.')
            detection = matches[0] if matches else None
            if detection is None: raise ValueError('Gewähltes Plugin unterstützt diesen Dokumenttyp nicht oder erkennt das PDF nicht.')
            selected = plugin, detection
        else:
            selected = select_plugin(document, plugins, errors=plugin_errors)
        if selected:
            plugin, detection = selected
            batch.document_type = detection.document_type
            batch.pdf_text = '\n\n'.join(f'--- Seite {n} ---\n{text}' for n, text in enumerate(pages, 1))
            result = plugin.parse(document, detection, ParseContext(batch))
            if fallback_pages:
                while len(result.pdf_booking_evidence) < len(result.transactions):
                    result.pdf_booking_evidence.append({})
                for evidence in result.pdf_booking_evidence:
                    # Plugins can combine account and amount data from several pages.
                    evidence['review_required'] = True
            result.plugin_id, result.plugin_version = plugin.plugin_id, plugin.version
            result.plugin_handler, result.detection_confidence = detection.handler_id, detection.confidence
            result.warnings.append(f'PDF-Plugin: {plugin.bank_name} · {detection.document_type} · Erkennung {detection.confidence:.0%}')
            result.warnings.extend('PDF-Plugin nicht geladen: ' + error for error in plugin_errors)
            from .booking_details import enrich_details
            from .models import enrich_tax_details
            for tx in result.transactions:
                if hasattr(tx, 'purpose'):
                    enrich_details(tx)
                enrich_tax_details(tx)
            _validate_plugin_batch(result, document)
            return result
        parse_generic_document(document, batch, document_tags)
        for evidence in batch.pdf_booking_evidence:
            if evidence.get('page') in fallback_pages:
                evidence['review_required'] = True
        batch.plugin_id, batch.plugin_version, batch.plugin_handler = 'generic.kontoauszug', '2.0', batch.document_type
        batch.warnings.extend('PDF-Plugin nicht geladen: ' + error for error in plugin_errors)
    except Exception as error:
        if batch.document_type == 'comdirect Finanzreport':
            from pdf_plugins._finanzreport_help import solution_for
            batch.transactions.clear()
            batch.balances.clear()
            batch.snapshots.clear()
            batch.documents.clear()
            batch.account_names.clear()
            batch.pdf_booking_evidence.clear()
            batch.errors.append('Finanzreport nicht importiert: ' + solution_for(error))
        else:
            if batch.document_type.startswith('Baader '):
                batch.transactions.clear()
                batch.snapshots.clear()
                batch.documents.clear()
                batch.pdf_booking_evidence.clear()
            batch.errors.append(f'PDF konnte nicht gelesen werden: {error}')
    return batch
