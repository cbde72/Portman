"""Actionable diagnostics shared by both comdirect report layouts."""
import re
from portfolio_v5.models import parse_date


def report_date(text):
    stamps = re.findall(r'Finanzreport\s+Nr\.\s*\d+\s+(?:per|vom)\s+(\d{2}\.\d{2}\.\d{4})', text, re.I)
    dates = {parse_date(stamp) for stamp in stamps}
    if len(dates) != 1 or None in dates or '' in dates:
        raise ValueError('Finanzreport: eindeutiger Stichtag fehlt. Lösung: Nur einen vollständigen Report pro PDF auswählen; Datum im Reportkopf prüfen.')
    return dates.pop()


def balance_error(name, opening, total, closing):
    def eur(value):
        return f'{value:.2f}'.replace('.', ',') + ' EUR'
    prefix = 'Finanzreport: Saldenprüfung fehlgeschlagen für ' + name + '. '
    if opening is None or closing is None:
        missing = ' und '.join(label for label, value in [('Anfangssaldo', opening), ('Endsaldo', closing)] if value is None)
        return prefix + missing + ' fehlt. Lösung: Vollständige Original-PDF einschließlich aller Umsatzseiten erneut auswählen.'
    return (prefix + f'Anfangssaldo {eur(opening)} + Buchungen {eur(total)} = {eur(opening + total)}; '
            f'Endsaldo im Report {eur(closing)}; Differenz {eur(closing - opening - total)}. '
            'Lösung: Umsatzseiten im Original auf fehlende oder abweichend gelesene Buchungen prüfen. '
            'Vollständige Original-PDF erneut laden; bei gleicher Abweichung Buchungen als Bank-CSV importieren.')


def solution_for(error):
    message = str(error)
    if 'Lösung:' in message:
        return message
    if 'IBAN' in message or 'Kontozuordnung' in message or 'Buchungskonto' in message or 'Kontonummer' in message:
        action = 'Kontoübersicht und Kontokopf in der Original-PDF prüfen und den vollständigen Report erneut laden. Bei widersprüchlichen Kennungen einen separaten Kontoauszug verwenden.'
    elif any(word in message for word in ('Depot', 'Wertpapier', 'Kurswert', 'Kaufwert')):
        action = 'Depotübersicht und Positionsseiten im Original prüfen. Bei nicht unterstütztem Layout Depotbestand als CSV/Excel und Kontoumsätze separat importieren.'
    elif 'datum' in message.lower() or 'Buchungstag' in message or 'datierte Zeile' in message:
        action = 'Buchungstag und Valuta auf den Umsatzseiten mit dem extrahierten Text vergleichen. Original-PDF erneut laden; bei gleichem Fehler Bank-CSV verwenden.'
    elif 'Endsaldo' in message:
        action = 'Saldo in der Kontoübersicht mit dem letzten Saldo der Umsatzseiten vergleichen. Nur zusammengehörige Seiten eines Reports auswählen.'
    else:
        action = 'Vollständige Original-PDF mit auswählbarem Text aus dem Bankarchiv erneut laden. Bei unverändertem Fehler einen separaten Kontoauszug oder Bank-CSV verwenden.'
    return message + ' Lösung: ' + action
