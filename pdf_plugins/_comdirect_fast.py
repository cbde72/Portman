"""Native text extraction with coordinates; use the regular reader on failure."""
import hashlib
import re
from portfolio_v5.models import ImportBatch
from pdf_plugins._comdirect_finanzreport_core import is_finanzreport, parse_finanzreport


def booking_columns(tx, lines, anchors, batch=None):
    """Read the labelled comdirect columns using native PDF coordinates."""
    from portfolio_v5.booking_details import enrich_details
    operation, recipient, purpose, amount = anchors
    fields = {'operation': [], 'counterparty': [], 'booking_text': [], 'bank_reference': []}
    for spans in lines:
        op, party, description = [], [], []
        left, outgoing = [], []
        for span in sorted(spans, key=lambda item: item['origin'][0]):
            x, text = span['origin'][0], span['text'].strip()
            if x < operation - 2: left.append(text)
            elif operation - 2 <= x < recipient - 2: op.append(text)
            elif recipient - 2 <= x < purpose - 2: party.append(text)
            elif purpose - 2 <= x < amount - 2: description.append(text)
            else: outgoing.append(text)
        value_date_row = (any(re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value) for value in left)
                          and not any(re.search(r'[+-]\d[\d.]*,\d{2}', value) for value in outgoing))
        value = ' '.join(op).strip()
        if value:
            (fields['bank_reference'] if value_date_row else fields['operation']).append(value)
        value = ' '.join(party).strip()
        iban = re.fullmatch(r'(DE(?: ?\d){20})(?:\s*/\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?))?', value)
        bic = re.fullmatch(r'(?:BIC\s*:?[ ]*)?([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)', value)
        if value_date_row and iban:
            tx.counterparty_iban = re.sub(r'\s+', '', iban[1])
            if iban[2]: tx.counterparty_bic = iban[2]
        elif value_date_row and bic:
            tx.counterparty_bic = bic[1]
        elif value:
            fields['counterparty'].append(value)
        if description: fields['booking_text'].append(' '.join(description))
    for field, values in fields.items():
        if values:
            setattr(tx, field, '\n'.join(dict.fromkeys(values)).strip())
            tx.field_sources[field] = 'comdirect Finanzreport · Tabellenspalte'
    for field in ('counterparty_iban', 'counterparty_bic'):
        if getattr(tx, field):
            tx.field_sources[field] = 'comdirect Finanzreport · Tabellenspalte'
    enrich_details(tx)
    from pdf_plugins._comdirect_finanzreport_core import enrich_interest_closing, stabilize_booking_references
    enrich_interest_closing(tx, batch)
    stabilize_booking_references(tx)


def try_fast_finanzreport(path, content):
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        with pymupdf.open(stream=content, filetype='pdf') as document:
            if document.needs_pass:
                return None
            if not len(document) or not is_finanzreport([document[0].get_text()]):
                return None
            pages = []
            layouts, columns = [], []
            for page in document:
                spans = [span for block in page.get_text('dict', flags=pymupdf.TEXTFLAGS_TEXT)['blocks']
                         if 'lines' in block for line in block['lines'] for span in line['spans']
                         if span['text'].strip()]
                if not spans:
                    return None  # Image-only pages still need the OCR/review path.
                spans.sort(key=lambda span: (span['origin'][1], span['origin'][0]))
                lines = []
                for span in spans:
                    baseline = span['origin'][1]
                    if not lines or abs(lines[-1][0] - baseline) > 2:
                        lines.append((baseline, []))
                    lines[-1][1].append(span)
                text = '\n'.join(' '.join(span['text'].strip() for span in
                    sorted(line, key=lambda span: span['origin'][0])) for _, line in lines)
                compact = ' '.join(text.split())
                visible = len(re.sub(r'\s', '', text))
                appendix = ('Übersicht Ihrer Kontodaten' in compact and
                            re.search(r'DE(?: ?\d){20}', compact))
                if (text.count('\ufffd') > visible * .05 or
                        (visible < 300 and page.get_images() and not appendix)):
                    return None  # A selectable letterhead may sit above a scanned table.
                pages.append(text)
                layouts.append([line for _, line in lines])
                words = page.get_text('words')
                anchors = [next((word[0] for word in words if word[4].startswith(label)), None)
                           for label in ('Vorgang', 'Auftraggeber', 'Buchungstext', 'Ausgang')]
                columns.append(anchors if all(x is not None for x in anchors) and anchors == sorted(anchors) else None)
        batch = ImportBatch(str(path), hashlib.sha256(content).hexdigest(), source_sheet='PDF')
        batch.pdf_text = '\n\n'.join(f'--- Seite {n} ---\n{text}' for n, text in enumerate(pages, 1))
        # Exactly the same cash and holdings reconciliation as the regular reader.
        batch = parse_finanzreport(batch, pages, content)
        offsets, flat = [], []
        for page, lines in enumerate(layouts):
            offsets.append(len(flat))
            flat.extend((page, line) for line in lines)
        starts = [offsets[e['page'] - 1] + e['line'] - 1 for e in batch.pdf_booking_evidence]
        for index, (tx, evidence) in enumerate(zip(batch.transactions, batch.pdf_booking_evidence)):
            anchors = columns[evidence['page'] - 1]
            if anchors is None:
                continue
            end = starts[index + 1] if index + 1 < len(starts) else len(flat)
            selected = []
            for _, spans in flat[starts[index]:end]:
                line = ' '.join(s['text'].strip() for s in sorted(spans, key=lambda s: s['origin'][0]))
                if line.startswith(('Neuer Saldo', 'Alter Saldo')):
                    break
                if line.startswith(('Finanzreport', 'Kundennummer', 'Kontonummer', 'comdirect',
                                    '25449 Quickborn', 'Buchungstag', 'Valuta', 'USt-ID:')):
                    continue
                selected.append(spans)
            booking_columns(tx, selected, anchors, batch)
            evidence['review_required'] = 'interest_reconciliation' in tx.field_sources
        return batch
    except Exception:
        return None
