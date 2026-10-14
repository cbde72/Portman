"""Fallback classification hints used by ISIN name lookup."""


def guess_region(name: str, isin: str) -> str:
    n = name.upper()
    if 'EMERGING' in n or ' EM ' in n or 'EMIMI' in n: return 'Emerging Markets'
    if 'USA' in n or 'U.S.' in n or 'S&P' in n or 'DOW' in n or isin.startswith('US'): return 'USA'
    if 'EUROPE' in n or 'EURO' in n or 'DAX' in n or isin.startswith('DE') or isin.startswith('NL'): return 'Europa'
    if 'JAPAN' in n or isin.startswith('JP'): return 'Japan'
    if 'WORLD' in n or 'MSCI WORLD' in n or 'GLOBAL' in n or 'DEV.MKT' in n: return 'Welt'
    if 'ASIA' in n or 'PACIFIC' in n: return 'Asien/Pazifik'
    return 'Sonstige'


def guess_cap_size(name: str) -> str:
    n = name.upper()
    if 'SMALL' in n or 'SML' in n: return 'Small'
    if 'MID' in n or 'MDAX' in n or '400' in n: return 'Mid'
    if 'LARGE' in n or 'TOP 100' in n or 'DAX' in n or 'S&P 500' in n: return 'Large'
    return 'Unbekannt'
