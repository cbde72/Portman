"""Classify PDF contents before attempting statement-table extraction."""
import re

from pdf_plugins._statement_bookings import HEADER

DOCUMENT_TAGS = {
    'Kontoauszug': ['Kontoauszug', 'monatlicher Kontoauszug'],
    'Steuerbescheinigung': ['Steuerbescheinigung', 'Jahres-Steuerbescheinigung', 'Jahressteuerbescheinigung'],
    'Zinsmitteilung': ['Zinsmitteilung'],
    'Wertpapierabrechnung': ['Wertpapierabrechnung', 'Wertpapier-Abrechnung'],
    'Depotauszug': ['Depotauszug', 'Depotaufstellung'],
    'Kosteninformation': ['Quartalsaufstellung', 'Kosteninformation', 'Kostenaufstellung'],
    'Wertpapierinformation': ['Wertpapierereignis', 'Wertpapier-Ereignis', 'Kapitalmaßnahme'],
    'Produktinformation': ['Factsheet', 'Basisinformationsblatt', 'Key Information Document'],
}


def normalized_document_tags(custom=None):
    """Return safe, non-empty parser tags with defaults for missing types."""
    result = {kind: list(tags) for kind, tags in DOCUMENT_TAGS.items()}
    if isinstance(custom, dict):
        for kind in DOCUMENT_TAGS:
            value = custom.get(kind)
            if isinstance(value, (list, tuple)):
                tags = list(dict.fromkeys(str(tag).strip() for tag in value if str(tag).strip()))
                if tags:
                    result[kind] = tags
    return result


def _contains_tag(text, tag):
    # Spaces in configured phrases also match line breaks and repeated spaces
    # produced by PDF extraction/OCR.
    pattern = r'(?<!\w)' + r'\s+'.join(re.escape(part) for part in tag.split()) + r'(?!\w)'
    return bool(re.search(pattern, text, re.I))


def classify_document(pages, tags=None):
    text = '\n'.join(pages)
    tags = normalized_document_tags(tags)
    # Explicit statement titles take priority over references in booking texts.
    if any(re.search(r'^\s*' + r'\s+'.join(re.escape(part) for part in tag.split()) + r'(?!\w)', text, re.I | re.M)
           for tag in tags['Kontoauszug']):
        return 'Kontoauszug'
    for label in tuple(DOCUMENT_TAGS)[1:]:
        if any(_contains_tag(text, tag) for tag in tags[label]):
            return label
    if any(_contains_tag(text, tag) for tag in tags['Kontoauszug']) or any(
            HEADER.search(line) for line in text.splitlines()):
        return 'Kontoauszug'
    return 'Unbekanntes Dokument'
