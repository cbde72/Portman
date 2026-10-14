"""Generic account-statement parsing used by external PDF plugins."""
import base64
import re

from portfolio_v5.models import BankDocument, parse_date


IDENTIFIER = re.compile(
    r'\b(?P<label>IBAN|(?:Depot|Konto)(?:nummer|[ -]?Nr\.?)?)'
    r'\s*[:：]?\s*(?P<value>DE(?: ?\d){20}|(?!DE)[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}|\d{1,3}(?:[ \t]+\d{3}){1,5}(?!\d)|\d{4,20}(?:[/-]\d{1,10})?)',
    re.IGNORECASE,
)


def analyse_pages(pages):
    candidates = {}
    for page_number, text in enumerate(pages, 1):
        for match in IDENTIFIER.finditer(text):
            label, value = match.group('label', 'value')
            value = re.sub(r'\s+', '', value).upper().rstrip('/-')
            if label.upper() == 'IBAN':
                if value.startswith('DE'):
                    value = value[:22]
                if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{11,30}', value):
                    continue
                name = 'IBAN ' + value
            else:
                name = ('Depot ' if label.lower().startswith('depot') else 'Konto ') + value
            candidates.setdefault(name, set()).add(page_number)
    return candidates


def parse_generic_document(document, batch, document_tags=None):
    pages = [page.text for page in document.pages]
    candidates = analyse_pages(pages)
    from pdf_plugins._statement_classification import classify_document
    batch.document_type = classify_document(pages, document_tags)
    booking_warnings = []
    if batch.document_type == 'Kontoauszug':
        from pdf_plugins._statement_bookings import parse_bookings
        batch.transactions, booking_warnings, batch.pdf_booking_evidence = parse_bookings(pages, analyse_pages)
    batch.warnings.extend(booking_warnings)
    page_by_number = {page.number: page for page in document.pages}
    for evidence in batch.pdf_booking_evidence:
        page = page_by_number.get(evidence['page'])
        evidence['ocr'] = bool(page and page.used_ocr)
        evidence['confidence'] = page.confidence if page else None
        evidence['review_required'] = evidence['ocr'] or bool(booking_warnings)
    for transaction, evidence in zip(batch.transactions, batch.pdf_booking_evidence):
        candidates.setdefault(transaction.account, set()).add(evidence['page'])
    for name in list(candidates):
        if name.startswith('Konto '):
            aliases = [iban for iban in candidates if iban.startswith('IBAN DE')
                and iban[-10:].lstrip('0') == name[6:].lstrip('0')]
            if len(aliases) == 1:
                candidates[aliases[0]].update(candidates.pop(name))
                for transaction in batch.transactions:
                    if transaction.account == name:
                        transaction.account = aliases[0]
    if not candidates:
        candidates = {'PDF ohne erkannte Kontonummer': set(range(1, len(pages) + 1))}
        batch.warnings.append('Kein Quellkonto erkannt. Zielkonto bitte manuell auswählen.')
    batch.warnings.append('Kontokennungen können auch Gegenkonten sein. Bitte prüfen oder auslassen. Erkannte Kontobuchungen stehen im Reiter „PDF-Buchungen“ zur Auswahl. Es werden keine Depotpositionen oder Salden erzeugt. Das vollständige Original wird jedem gewählten Konto zugeordnet.')
    if not batch.transactions:
        if batch.document_type == 'Kontoauszug':
            batch.warnings.append('Kontoauszug erkannt, aber keine unterstützte Buchungstabelle erkannt; nur Dokumentablage. Bitte Buchungen am Original prüfen.')
        else:
            batch.warnings.append(f'{batch.document_type}: nur Dokumentablage; keine Kontobuchungen übernommen.')
    encoded = base64.b64encode(document.content).decode('ascii')
    for name, page_numbers in candidates.items():
        relevant = '\n'.join(pages[n - 1] for n in sorted(page_numbers))
        date_match = re.search(r'(?:Datum|vom|Stand(?:\s+zum)?)\s*:?\s*(\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})', relevant, re.I)
        document_date = parse_date(date_match.group(1)) if date_match else ''
        batch.documents.append(BankDocument(name, batch.file_hash + ':' + name,
            document.path.name, document_date or '', encoded))
        batch.warnings.append(f'{name}: erkannt auf Seite(n) ' + ', '.join(map(str, sorted(page_numbers))))
    batch.pdf_text = '\n\n'.join(f'--- Seite {n} ---\n{text}' for n, text in enumerate(pages, 1))
    return batch
