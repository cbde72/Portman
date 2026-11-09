"""Independent comdirect handlers; no V09 compatibility layer."""
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from itertools import product
import re
from portman_parsers.api import (
    Account, AccountBalance, AccountFunction, AccountType, AdvanceTaxCalculation, AdvanceTaxCarryforward,
    CashMovement, CashMovementType, CashStatus, CostEvent, CostInformationType, Depot, DepotAccountLink, ExchangeRate,
    DepotPosition, DepotSnapshot, DepotType, Detection, Evidence, FeeEffect, FeeEvent, FieldValue,
    FinancialEvent, Issue, IssueNature, IssueSeverity, MissingValue, ParsedDocument, ReviewStatus,
    ReversalDetails, SecurityMovement, SecurityTrade, TaxApprovalStatus, TaxComponent, TaxEvent,
)
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id

A=r"\d[\d.]*,\d+"; D=r"\d{2}\.\d{2}\.\d{4}"
TITLES=(("kosteninformation_mifid_ii",r"Kosteninformation\s+zum\s+Wertpapiergesch"),("vorabpauschale",r"Steuerliche\s+Behandlung:\s*Vorabpauschale"),("investment_ausschuettung",r"Steuerliche\s*Behandlung:.*Investment-Aussch"),("dividende_steuer_inland",r"Steuerliche\s*Behandlung:.*Dividende"),("dividendengutschrift",r"Abrechnung\s*Dividendengutschrift"),("ertragsgutschrift",r"Abrechnung\s*Ertragsgutschrift"),("einloesung",r"Abrechnung\s*Einl[öo]sung"),("wertpapierkauf",r"Wertpapierkauf"),("wertpapierverkauf",r"Wertpapierverkauf"))
ISIN=re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b"); IBAN=re.compile(r"DE(?:\s*\d){20}"); DEPOT=re.compile(r"Depot(?:nummer|nr\.)\s*:?\s*(\d+(?:\s+\d+)?)",re.I)
# comdirect klebt Kennungen und Namen ohne Trennzeichen aneinander, z. B.
# "A0H074iSh.DJ ..." oder "DE0007164600Inhaber-Aktien".  Deshalb werden
# Kandidaten ohne nachlaufende Wortgrenze gesucht und anschließend validiert.
ISIN_CANDIDATE=re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
WKN_CANDIDATE=re.compile(r"(?<![A-Z0-9])[A-Z0-9]{6}")
IDENTITY_HEADER=re.compile(r"Wertpapier\s*-?\s*Bezeichnung.*?(?:WKN|WPKNR)\s*/\s*ISIN",re.I)
IDENTITY_ROW_STOP=re.compile(r"^(?:Emissionsland|zahlbar|Abrechnung|Bruttobetrag|Zu\s+Ihren|Verrechnung|Information|Ihre\s+comdirect|Gesch(?:ä|ae)ftstag|Schlusstag|Ausf(?:ü|ue)hrungstag|Ausf(?:ü|ue)hrung|Depot|IBAN|Valuta|Kurs|Kurswert|Provision|Steuer|Referenz|F(?:ä|ae)lligkeit|Nennwert|Gesch(?:ä|ae)ftsnummer|Rechnungsnummer|Kundennr|BLZ|Telefon)\b",re.I)
IDENTITY_ROW_PREFIX=re.compile(r"^\s*(?:p\s*e\s*r\s+\d{2}\.\d{2}\.\d{4}|(?:S\s*T\s*K)\.?\s*-?\s*[\d.,]+)\s*",re.I)  # Layouttext trennt Buchstaben ("p er", "S TK")
IDENTITY_REASON={"PARTIAL":"nur WKN oder Name erkannt","AMBIGUOUS":"mehrere Kennungen im selben Wertpapierblock","INVALID":"ISIN-Prüfziffer oder ISIN-Format ungültig"}
QTY=re.compile(r"(?:Stk\.?|STK)\s*("+A+r")",re.I); NENNWERT_QTY=re.compile(r"Nennwert\s*Zum\s*(?:Misch)?Kurs\s*von\s*(?:St\.?|Stk\.?)\s*("+A+r")",re.I); VALUTA=re.compile(r"(?:Valuta|zahlbar\s+ab)\s*("+D+r")",re.I)
DIVIDEND_REVERSAL=re.compile(r"\bStorno\s*[-–]?\s*Abrechnung\s+(?:Dividenden|Ertrags)gutschrift\b",re.I)
ORIGINAL_REFERENCE=re.compile(r"\bReferenz\s+(?:der|zur)\s+ursprünglichen\s+(?:Abrechnung|Gutschrift)\s*:?\s*([A-Z0-9][A-Z0-9-]{5,39})",re.I)
ORIGINAL_EX_DATE=re.compile(r"\bEx[- ]Tag(?:\s+der\s+ursprünglichen\s+(?:Dividenden-)?Gutschrift)?\s*:?\s*("+D+r")",re.I)
ORIGINAL_PAYMENT_DATE=re.compile(r"\b(?:Zahlungs|Zahlungs-)tag(?:\s+der\s+ursprünglichen\s+(?:Dividenden-)?Gutschrift)?\s*:?\s*("+D+r")|\bZahltag(?:\s+der\s+ursprünglichen\s+(?:Dividenden-)?Gutschrift)?\s*:?\s*("+D+r")",re.I)
ORIGINAL_BUSINESS_DATE=re.compile(r"\bGeschäftstag\s+der\s+ursprünglichen\s+(?:Abrechnung|Gutschrift)\s*:?\s*("+D+r")",re.I)
ORIGINAL_VALUE_DATE=re.compile(r"\bValuta\s+der\s+ursprünglichen\s+(?:Abrechnung|Gutschrift)\s*:?\s*("+D+r")",re.I)
ORIGINAL_BOOKING_DATE=re.compile(r"\bBuchungstag\s+der\s+ursprünglichen\s+(?:Abrechnung|Gutschrift)\s*:?\s*("+D+r")",re.I)
ORIGINAL_QUANTITY=re.compile(r"\b(?:Stückzahl|Stück|Nominale)\s+der\s+ursprünglichen\s+Gutschrift\s*:?\s*(?:STK\s*)?("+A+r")",re.I)
TAX_YEAR=re.compile(r"(?:Steuerjahr|Veranlagungsjahr)\s*:?\s*((?:19|20)\d{2})\b",re.I)
FSA_CONSUMPTION=re.compile(r"(?:Verbrauch(?:ter)?\s+(?:des\s+)?Freistellungsauftrags|Freistellungsauftrag\s+(?:verbraucht|genutzt))\s*:?\s*(?:EUR\s*)?("+A+r")",re.I)
WKN=re.compile(r"\bWKN\s*:?[ \t]*([A-Z0-9]{6})\b",re.I)
BANK_REFERENCE=re.compile(r"\bReferenz(?!\s+(?:der|zur)\s+ursprünglichen)(?:\s*[- ]?\s*(?:Nr\.?|nummer))?\s*:?\s*([A-Z0-9][A-Z0-9\s]*?)(?=\s*(?:Referenz|Depotnummer|Depotnr|Kundennummer|comdirect)|[^A-Z0-9\s]|\n\s*\n|$)",re.I)
LIQUIDATION_ADJUSTMENT=re.compile(r"\bNachbesserung[ \t]+(?:Liquizlg\b\.?|Liquidationszahlung\b)(?:[ \t]+(ETF[0-9]{3})\b)?",re.I)
SETTLEMENT_DATE=re.compile(r"\b("+D+r")\b")
SETTLEMENT_COLUMNS=re.compile(r"Verrechnung\s+über\s+Konto\s*\(IBAN\)(?P<columns>[^\n]{0,180})",re.I)
SETTLEMENT_ROW_DATE=re.compile(r"DE(?:\s*\d){20}\s+[A-Z]{3}\s+(?P<date>"+D+r")\s+[A-Z]{3}\s+[+-]?"+A,re.I)
TRADE_LINE=re.compile(r"Stk\.?\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s+(?P<name>.+?)\s*,?\s*WKN\s*/\s*ISIN\s*:\s*(?P<wkn>[A-Z0-9]{6})\s*/\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)",re.I)
TRADE_EXECUTION=re.compile(r"Nennwert\s*Zum\s*(?:Misch)?Kurs\s*von\s*(?:St\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s*)?EUR\s*(?P<price>\d[\d.]*(?:,\d+)?)\s*Kurswert\s*:?\s*EUR\s*(?P<market>"+A+r")",re.I)
TRADE_DAY=re.compile(r"(?:Wertpapierkauf|Wertpapierverkauf|Gesch\.ftsvorgang)\s*Nr\.?\s*\d+\s*vom\s*("+D+r")",re.I)
TRADE_DATE=re.compile(r"(?:Geschäftstag|Schlusstag)\s*:?[ \t]*("+D+r")",re.I)
EXECUTION_DATE=re.compile(r"(?:Ausführungstag|Ausführung)\s*:?[ \t]*("+D+r")",re.I)
PRICE=re.compile(r"(?:Ausführungskurs|Kurs)\s*:?[ \t]*(?:(?P<cur1>[A-Z]{3})\s*)?(?P<a>"+A+r")(?:\s*(?P<cur2>[A-Z]{3}))?",re.I)
MARKET_VALUE=re.compile(r"(?:Kurswert|Gegenwert)\s*:?[ \t]*(?P<cur>[A-Z]{3})\s*(?P<a>"+A+r")",re.I)
GROSS=re.compile(r"(?:Bruttobetrag|Bruttoertrag|Bruttodividende)\s*:?[ \t]*(?P<cur>[A-Z]{3})\s*(?P<a>"+A+r")",re.I)
FX=re.compile(r"(?:Devisenkurs|Umrechnungskurs)\s*:?[ \t]*("+A+r")",re.I)
EXPLICIT_FX_PAIR=re.compile(r"(?:Devisen|Umrechnungs)?kurs(?:\s+am\s+(?P<date>"+D+r"))?\s*:?\s*1\s+(?P<base>[A-Z]{3})\s*=\s*(?P<rate>\d[\d.]*,\d+)\s+(?P<quote>[A-Z]{3})\b",re.I)
NAME=re.compile(r"(?:Wertpapierbezeichnung|Bezeichnung)\s*:?[ \t]*(.+)",re.I)
SETTLE=re.compile(r"(?:Zu\s*Ihren\s*(?P<dir>Lasten|Gunsten)|(?:^|\n)Gutschrift|(?:^|\n)Zahlungsbetrag).{0,80}?(?P<cur>[A-Z]{3})\s*-?\s*(?P<a>"+A+r")",re.I|re.S)
TAX=(("CAPITAL_GAINS_TAX",r"Kapitalertragsteuer\s*(?:EUR)?\s*-?("+A+r")"),("SOLIDARITY_SURCHARGE",r"Solidarit.tszuschlag\s*(?:EUR)?\s*-?("+A+r")"),("CHURCH_TAX",r"Kirchensteuer\s*(?:EUR)?\s*-?("+A+r")"),("WITHHOLDING_TAX",r"Quellensteuer\s*(?:[A-Z]{3})?\s*-?("+A+r")"))
FEE=(("provision",r"Provision\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("foreign_expenses",r"(?:Fremdspesen|fremde\s+Spesen)\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("exchange_fee",r"(?:B.rsenplatz.*Entgelt|B.rsengeb.hr)\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("clearing_fee",r"Abwickl\S*entgelt\s*Clearstream\s*:?\s*(?:EUR)?\s*-?("+A+r")"))
# Gebührenzeilen in defekter Schrift: Bezeichnung lesbar (bzw. mit verschobenen Großbuchstaben), Doppelpunkt, "EUR" und Betrag verschlüsselt.
CIPHER_FEE_LABELS=(("provision",r"P?rovision"),("clearing_fee",r"\Sbwickl\Sentgelt{sp}\Slearstream"),("exchange_fee",r"\S.rsenplatzabh.ng\S{sp}\Sntgelt"))
CIPHER_TRADE=re.compile(r"Nennwert\s*Zum\s*(?:Misch)?[Kk]urs\s*von\s*\n\s*St\S(?P<sp>\S)(?P=sp)*(?P<qty>(?:(?!(?P=sp))\S)+)(?P=sp)+\SUR(?P=sp)+(?P<price>\S+?)(?P=sp)*\n"
                        r"(?P=sp)*Kurswert(?P=sp)+\S(?P=sp)\SUR(?P=sp)+(?P<market>\S+?)(?P=sp)*\n")
CIPHER_ACCOUNT=re.compile(r"Steuern\s*\nDE(?P<iban>\S+?)(?P<sp>\S)\SUR(?P=sp)+(?P<valuta>\S{10})")
NUMBER_TEXT=re.compile(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?")
CIPHER_DATE=re.compile(r"ftstag(\S)\1*\S\1(\S{10})"); CIPHER_NUMBER=re.compile(r"nummer(\S)\1*\S\1((?:(?!\1)\S)+)\1((?:(?!\1)\S)+)")


def _cipher_trade(head,tail):
  """Entschlüsselt Stückzahl, Kurs und Kurswert aus Seite 1 mit defekter Schrift.

  comdirect bettet je Dokument eine Schrift ohne Unicode-Zuordnung ein; die Zeichen
  sind aufsteigend sortiert, aber je Variante verschoben. Der Schlüssel wird aus dem
  lesbaren Steuerabschnitt gewonnen; bis zu zwei fehlende Ziffern werden über die
  Sortierung eingegrenzt. Werte gelten nur bei genau einer Lösung mit Stück x Kurs = Kurswert.
  """
  trade=CIPHER_TRADE.search(head)
  if not trade: return None
  line=TRADE_LINE.search(tail); settle=re.search(r"Lasten\s*vor\s*Steuern:?\s*EUR\s*-?("+A+r")",tail,re.I)
  day=re.search(r"\bvom\s*("+D+r")",tail); number=re.search(r"\bNr\.\s*(\d{6,})",tail)
  coded_day=CIPHER_DATE.search(head); coded_number=CIPHER_NUMBER.search(head)
  account=re.search(r"Valuta\s*("+D+r")\s*auf\s*Konto\s*EUR\s*mit\s*der\s*IBAN\s*DE(\d[\d ]*\d)",tail); coded_account=CIPHER_ACCOUNT.search(head)
  plain_qty=line and line.group("qty")
  # Der Steuerabschnitt ergänzt Nachkommanullen ("2,230" statt "2,23"); auf ganze Stück gekürzte Werte sind kein belegter Anker.
  while plain_qty and len(plain_qty)>len(trade["qty"]) and "," in plain_qty and plain_qty.endswith("0"): plain_qty=plain_qty[:-1]
  pairs=((trade["qty"],plain_qty),(coded_day and coded_day.group(2),day and day.group(1)),
         (coded_number and coded_number.group(2)+coded_number.group(3),number and number.group(1)),
         (coded_account and coded_account["iban"].replace(coded_account["sp"],"")+coded_account["valuta"],
          account and account.group(2).replace(" ","")+account.group(1)))
  key={}
  for coded,plain in pairs:
   if coded and plain and len(coded)==len(plain):
    for c,p in zip(coded,plain):
     if key.setdefault(c,p)!=p: return None

  def solve(key):
   # Der Kurswert hat immer zwei Nachkommastellen; damit ist das Komma-Zeichen bekannt.
   key=dict(key)
   if len(trade["market"])>3 and key.setdefault(trade["market"][-3],",")!=",": return []
   if len(set(key.values()))!=len(key): return []
   known={int(p):c for c,p in key.items() if p.isdigit()}
   unknown=sorted({c for name in ("qty","price","market") for c in trade[name]}-set(key))
   def candidates(code):
    return [str(d) for d in range(10) if d not in known
            and all(c<code for k,c in known.items() if k<d) and all(c>code for k,c in known.items() if k>d)]
   solutions=[]
   for digits in product(*(candidates(code) for code in unknown)) if len(unknown)<=2 else ():
    if len(set(digits))<len(digits): continue
    trial={**key,**dict(zip(unknown,digits))}
    try:
     texts=["".join(trial[c] for c in trade[name]) for name in ("qty","price","market")]
     # dec() entfernt Punkte; ein als Ziffer geratener Tausenderpunkt darf deshalb nicht durchrutschen.
     if not all(NUMBER_TEXT.fullmatch(t) for t in texts): continue
     qty,price,market=(dec(t) for t in texts)
    except (KeyError,ArithmeticError,ValueError):
     continue
    if qty>0 and (qty*price).quantize(Decimal("0.01"),ROUND_HALF_UP)==market: solutions.append((qty,price,market,trial))
   return solutions

  solutions=solve(key)
  # Die Belastung entspricht dem Kurswert nur ohne Entgelte; sie gilt daher nur, wenn der entschlüsselte Kurswert ihr exakt entspricht.
  if len(solutions)!=1 and settle and len(settle.group(1))==len(trade["market"]):
   hint=dict(zip(trade["market"],settle.group(1)))
   if all(key.get(c,p)==p for c,p in hint.items()):
    solutions=[x for x in solve({**hint,**key}) if x[2]==dec(settle.group(1))]
  return solutions[0] if len(solutions)==1 else None


def _cipher_fees(head,tail,cipher):
  """Entschlüsselt Gebührenzeilen mit dem Schlüssel aus `_cipher_trade`.

  Ein Wert gilt nur, wenn jedes Zeichen im belegten Schlüssel steht und der Kurswert
  zuzüglich aller entschlüsselten Gebühren exakt der lesbaren Belastung vor Steuern
  entspricht. Wie in `_cipher_trade` werden bis zu zwei unbekannte Ziffern nur über die
  aufsteigende Sortierung der Schrift eingegrenzt; es muss genau eine Lösung bleiben.
  Sonst bleiben die Gebühren leer; es werden keine Beträge abgeleitet.
  """
  trade=CIPHER_TRADE.search(head); settle=re.search(r"Lasten\s*vor\s*Steuern:?\s*EUR\s*-?("+A+r")",tail,re.I)
  if not (cipher and trade and settle): return ()
  sp=re.escape(trade["sp"]); key=cipher[3]; coded=[]
  for kind,label in CIPHER_FEE_LABELS:
   line=re.compile(r"(?:^|\n)"+sp+r"*(?:"+label.format(sp=sp)+r")"+sp+r"+\S"+sp+r"\SU\S?"+sp+r"+(?P<amt>(?:(?!"+sp+r")\S)+)"+sp+r"*(?:\n|$)")
   coded+=[(kind,match["amt"]) for match in line.finditer(head)]
  if not coded or len({k for k,_ in coded})!=len(coded): return ()
  known={int(p):c for c,p in key.items() if p.isdigit()}
  unknown=sorted({c for _,amount in coded for c in amount}-set(key))
  if len(unknown)>2: return ()
  def candidates(code):
   return [str(d) for d in range(10) if d not in known
           and all(c<code for k,c in known.items() if k<d) and all(c>code for k,c in known.items() if k>d)]
  solutions=[]
  for digits in product(*(candidates(code) for code in unknown)):
   if len(set(digits))<len(digits): continue
   trial={**key,**dict(zip(unknown,digits))}
   texts=["".join(trial[c] for c in amount) for _,amount in coded]
   if not all(re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}",t) for t in texts): continue
   fees=tuple((kind,dec(t)) for (kind,_),t in zip(coded,texts))
   if cipher[2]+sum(a for _,a in fees)==dec(settle.group(1)): solutions.append(fees)
  return solutions[0] if len(solutions)==1 else ()


@dataclass(frozen=True)
class _SecurityIdentity:
  name: str | None = None
  wkn: str | None = None
  isin: str | None = None
  status: str = "NOT_FOUND"
  reason: str = ""
  name_rows: tuple[str, ...] = ()
  name_source: str | None = None


def _valid_isin(value):
  value = re.sub(r"\s+", "", str(value or "")).upper()
  if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
   return False
  digits = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
  total = sum((int(char) * (2 if (len(digits) - index) % 2 == 0 else 1)) // 10 +
              (int(char) * (2 if (len(digits) - index) % 2 == 0 else 1)) % 10
              for index, char in enumerate(digits))
  return total % 10 == 0


def _join_spaced_letters(value):
  """Repair PDF glyph spacing only for an unambiguous letter run."""
  value = re.sub(r"\s+", " ", str(value or "")).strip()
  pattern = re.compile(r"(?<![\wÄÖÜäöüß])(?:[A-Za-zÄÖÜäöüß]\s+){3,}[A-Za-zÄÖÜäöüß](?![\wÄÖÜäöüß])")
  def collapse(match):
   return re.sub(r"\s+", "", match.group(0))
  value = pattern.sub(collapse, value)
  value = re.sub(r"\s*-\s*", "-", value)
  value = re.sub(r"\s*\.\s*", ".", value)
  value = re.sub(r"(?<=[A-Za-zÄÖÜäöüß])o\.N\.", " o.N.", value, flags=re.I)
  return value


def _isin_candidates(value):
  """Return ISIN candidates with offsets, tolerating glued surrounding text.

  A candidate must not be embedded in a longer digit run.  Checksum validity
  is returned separately so invalid identifiers can be reported as INVALID
  instead of silently disappearing.
  """
  result = []
  for match in ISIN_CANDIDATE.finditer(value):
    start, end = match.span()
    if start and value[start - 1].isdigit():
     continue
    if end < len(value) and value[end].isdigit():
     continue
    candidate = match.group(0).upper()
    result.append((candidate, start, end, _valid_isin(candidate)))
  return result


def _wkn_candidates(value, isin_spans):
  """Find WKN candidates without reusing characters of an ISIN.

  A WKN is six alphanumeric characters and always contains at least one digit.
  The missing trailing word boundary is intentional: comdirect writes
  ``716460SAP SE`` and ``A0H074iSh.DJ ...``.
  """
  result = []
  for match in WKN_CANDIDATE.finditer(value):
    candidate = match.group(0).upper()
    if not any(char.isdigit() for char in candidate):
     continue
    if match.end() < len(value) and value[match.end()].isdigit():
     continue
    if any(match.start() < end and start < match.end() for start, end in isin_spans):
     continue
    result.append((candidate, match.start(), match.end()))
  return result


def _identity_fragments(row, isins, wkns):
  """Split an identity row into name fragments around all identifiers."""
  spans = sorted({(start, end) for _, start, end, _ in isins} |
                 {(start, end) for _, start, end in wkns})
  parts = []
  cursor = 0
  for start, end in spans:
   if cursor < start:
    parts.append(row[cursor:start])
   cursor = max(cursor, end)
  if cursor < len(row):
   parts.append(row[cursor:])
  fragments = []
  for part in parts:
   part = IDENTITY_ROW_PREFIX.sub("", part).strip(" \t,;")
   if part and re.search(r"[A-Za-zÄÖÜäöüß]", part):
    fragments.append(part)
  return fragments


def _strip_country_artifact(fragment, country):
  """Drop the country prefix that comdirect places before the ISIN row.

  Only a standalone trailing token equal to the ISIN country is removed.
  Legal suffixes such as ``SE`` are never treated as artefacts.
  """
  if country and country != "SE" and re.search(rf"\s{re.escape(country)}$", fragment):
   return re.sub(rf"\s{re.escape(country)}$", "", fragment).strip()
  return fragment


def _extract_comdirect_security_identity(text, layout_text=None):
  """Extract one validated identity block, including glued identifiers."""
  source = layout_text or text
  lines = source.splitlines()
  for index, header in enumerate(lines):
   if not IDENTITY_HEADER.search(header):
    continue
   rows = []
   for line in lines[index + 1:index + 6]:
    if not line.strip() or IDENTITY_ROW_STOP.match(line.strip()):
     break
    rows.append(line)
    if len(rows) == 4:
     break
   if not rows:
    continue
   parsed = []
   for row in rows:
    isins = _isin_candidates(row)
    raw_isin_spans = [match.span() for match in ISIN_CANDIDATE.finditer(row)]
    wkns = _wkn_candidates(row, raw_isin_spans)
    adjustment_name = LIQUIDATION_ADJUSTMENT.search(row)
    if adjustment_name and adjustment_name.group(1) and any(item[3] for item in isins) and any(entry[2] for entry in parsed):
     # Die ETF-Nummer in der Namensfortsetzung ist keine zweite WKN.
     wkns = [item for item in wkns if item[1:] != adjustment_name.span(1)]
    parsed.append((row, isins, wkns))
   identifier_rows = [position for position, (_, isins, wkns) in enumerate(parsed) if isins or wkns]
   if not identifier_rows:
    continue
   valid_isins = [item for _, isins, _ in parsed for item in isins if item[3]]
   invalid_isins = [item for _, isins, _ in parsed for item in isins if not item[3]]
   distinct_isins = tuple(dict.fromkeys(item[0] for item in valid_isins))
   distinct_wkns = tuple(dict.fromkeys(item[0] for _, _, wkns in parsed for item in wkns))
   if len(distinct_wkns) > 1 or len(distinct_isins) > 1:
    return _SecurityIdentity(status="AMBIGUOUS", reason=IDENTITY_REASON["AMBIGUOUS"])
   if invalid_isins and not valid_isins:
    return _SecurityIdentity(status="INVALID", reason=IDENTITY_REASON["INVALID"])
   wkn = distinct_wkns[0] if distinct_wkns else None
   isin = distinct_isins[0] if distinct_isins else None
   country = isin[:2] if isin else None
   fragments = []
   first_identifier, last_identifier = identifier_rows[0], identifier_rows[-1]
   for position, (row, isins, wkns) in enumerate(parsed):
    if isins or wkns:
     fragments.extend(_identity_fragments(row, isins, wkns))
    elif position < first_identifier or first_identifier < position < last_identifier:
     # Namensfortsetzung ohne eigene Kennung, aber keine Fremdzeile danach.
     continuation = IDENTITY_ROW_PREFIX.sub("", row).strip()
     if continuation:
      fragments.append(continuation)
   name_rows = tuple(dict.fromkeys(
     cleaned for cleaned in (_join_spaced_letters(_strip_country_artifact(fragment, country))
                             for fragment in fragments if fragment) if cleaned))
   name = " ".join(name_rows) or None
   status = "RECOGNIZED" if isin else "PARTIAL" if (wkn or name) else "NOT_FOUND"
   reason = IDENTITY_REASON.get(status, "")
   name_source = rows[identifier_rows[0]] if identifier_rows else None
   return _SecurityIdentity(name, wkn, isin, status, reason, name_rows, name_source)
  return _SecurityIdentity()


def extract_comdirect_security_identity(text, layout_text=None):
  """Backward-compatible tuple API for the validated identity extractor."""
  identity = _extract_comdirect_security_identity(text, layout_text)
  return identity.name, identity.wkn, identity.isin


def _document_layout_text(document):
  try:
   import json
   pages = json.loads(document.metadata.get("text_preparation_json", "{}"))
   return "\n".join(page.get("layout_text", "") for page in pages.get("pages", ()) if page.get("layout_text"))
  except (AttributeError, TypeError, ValueError):
   return ""

def _squash(text):
  """Whitespace-free lowercase form for locating cleaned excerpts (e.g. repaired glyph spacing)."""
  return re.sub(r"\s+","",str(text)).lower()

def _page_for_offset(document,offset):
  """Map a character offset within the joined document text to its PDF page."""
  consumed=0
  for page in document.pages:
    consumed+=len(page.text)
    if offset<consumed: return page.number
    consumed+=1  # newline joining consecutive pages
  return document.pages[-1].number

def evidence_page(document,excerpt,offset=None,alternatives=()):
  """Determine the PDF page of a finding without guessing a default page.

  Regex matches carry their exact offset in the joined text; raw values are
  located per page, including a whitespace-insensitive pass for values that
  were cleaned (for example collapsed glyph spacing in security names).
  Unlocatable excerpts raise instead of silently claiming page 1.
  """
  if offset is not None and 0<=offset<=len(document.text): return _page_for_offset(document,offset)
  for page in document.pages:
    if excerpt in page.text: return page.number
  for candidate in (excerpt,*alternatives):
    key=_squash(candidate)
    if key:
     for page in document.pages:
      if key in _squash(page.text): return page.number
  raise ValueError(f"evidence excerpt does not occur in any PDF page: {str(excerpt)[:60]!r}")

def _original_excerpt(document,candidates):
  """Return the first candidate as it literally occurs in a PDF page, else None.

  Names are normalised (layout text, collapsed glyph spacing, row order), so a
  candidate may differ from the page text only by whitespace.  In that case the
  original page span is returned, never the normalised text and never a
  substitute finding.
  """
  for candidate in candidates:
    if not candidate or not str(candidate).strip(): continue
    candidate=str(candidate)
    for page in document.pages:
      if candidate in page.text: return candidate
    key=_squash(candidate)
    if not key: continue
    for page in document.pages:
      positions=[i for i,ch in enumerate(page.text) if not ch.isspace()]
      squashed="".join(page.text[i] for i in positions).lower()
      start=squashed.find(key)
      if start>=0: return page.text[positions[start]:positions[start+len(key)-1]+1]
  return None

def evidence_recorder(document,plugin_id,handler_id,plugin_version):
  """Evidence factory whose field values always share the evidence page.

  ``ev`` accepts a regex match (exact page via match offset) or a plain value
  (located per page).  ``fv`` builds a PDF FieldValue with the page of the
  referenced Evidence, never a hardcoded page number.
  """
  evidence=[]; pages={}
  def ev(field,source,*alternatives,offset=None):
    excerpt=source.group(0) if hasattr(source,"group") else str(source)
    if offset is None and hasattr(source,"start"): offset=source.start()
    page=evidence_page(document,excerpt,offset,alternatives)
    eid=stable_id("evidence",document.document_id,page,field,excerpt,len(evidence))
    evidence.append(Evidence(eid,document.document_id,page,field,excerpt,f"page:{page}",document.source_hash,plugin_id,handler_id,plugin_version)); pages[eid]=page; return eid
  def fv(value,eid,review_status=ReviewStatus.UNREVIEWED):
    return FieldValue.from_pdf(value,pages[eid],eid,review_status=review_status)
  return ev,fv,evidence

def dec(v): return Decimal(v.replace(".","").replace(",","."))
def date(v): return datetime.strptime(v,"%d.%m.%Y").date()

def _settlement_column_date(text):
 """Return a payment-row date only when the same table explicitly labels its meaning."""
 headers=tuple(SETTLEMENT_COLUMNS.finditer(text))
 if len(headers)!=1: return None
 header=headers[0]
 label=re.search(r"\b(Valuta|Buchungstag)\b",header.group("columns"),re.I)
 if not label: return None
 row=SETTLEMENT_ROW_DATE.search(text,header.end(),min(len(text),header.end()+500))
 if not row: return None
 date_match=re.compile(D).search(text,row.start("date"),row.end("date"))
 return (date(row.group("date")),"value_date" if label.group(1).casefold()=="valuta" else "booking_date",date_match)

def _reversal_details(text,ev):
 """Extract only facts explicitly attributed to the original credit."""
 reference=ORIGINAL_REFERENCE.search(text); ex_date=ORIGINAL_EX_DATE.search(text)
 payment_date=ORIGINAL_PAYMENT_DATE.search(text); booking_date=ORIGINAL_BOOKING_DATE.search(text)
 business_date=ORIGINAL_BUSINESS_DATE.search(text); value_date=ORIGINAL_VALUE_DATE.search(text)
 quantity=ORIGINAL_QUANTITY.search(text)
 reference_id=ev("reversal_original_reference",reference) if reference else None
 ex_date_id=ev("reversal_original_ex_date",ex_date) if ex_date else None
 payment_date_id=ev("reversal_original_payment_date",payment_date) if payment_date else None
 business_date_id=ev("reversal_original_business_date",business_date) if business_date else None
 value_date_id=ev("reversal_original_value_date",value_date) if value_date else None
 booking_date_id=ev("reversal_original_booking_date",booking_date) if booking_date else None
 quantity_id=ev("reversal_original_quantity",quantity) if quantity else None
 return ReversalDetails(
     original_reference=reference.group(1) if reference else MissingValue.UNKNOWN,
     original_reference_evidence_ids=(reference_id,) if reference_id else (),
     original_ex_date=date(ex_date.group(1)) if ex_date else MissingValue.UNKNOWN,
     original_ex_date_evidence_ids=(ex_date_id,) if ex_date_id else (),
     original_payment_date=date(next(value for value in payment_date.groups() if value)) if payment_date else MissingValue.UNKNOWN,
     original_payment_date_evidence_ids=(payment_date_id,) if payment_date_id else (),
     original_business_date=date(business_date.group(1)) if business_date else MissingValue.UNKNOWN,
     original_business_date_evidence_ids=(business_date_id,) if business_date_id else (),
     original_value_date=date(value_date.group(1)) if value_date else MissingValue.UNKNOWN,
     original_value_date_evidence_ids=(value_date_id,) if value_date_id else (),
     original_booking_date=date(booking_date.group(1)) if booking_date else MissingValue.UNKNOWN,
     original_booking_date_evidence_ids=(booking_date_id,) if booking_date_id else (),
     quantity=dec(quantity.group(1)) if quantity else MissingValue.UNKNOWN,
     quantity_evidence_ids=(quantity_id,) if quantity_id else (),
 )

class ComdirectPlugin:
 metadata=next(x for x in APPROVED_PLUGINS if x.plugin_id=="user.comdirect-ertraege")
 def detect(self,doc):
  if not re.search("comdirect",doc.text,re.I): return ()
  for h,p in TITLES:
   if re.search(p,doc.text,re.I|re.S):
    return (Detection(self.metadata.plugin_id,self.metadata.version,h,next(x.document_type for x in self.metadata.handlers if x.handler_id==h),Decimal("0.98"),"comdirect title recognized"),)
  return ()
 def parse(self,doc,d):
  text=doc.text; ev,fv,evidence=evidence_recorder(doc,self.metadata.plugin_id,d.handler_id,self.metadata.version)
  title=re.search(next(p for h,p in TITLES if h==d.handler_id),text,re.I|re.S); eid=ev("document_type",title)
  layout = _document_layout_text(doc)
  identity = _extract_comdirect_security_identity(text, layout)
  security_name, column_wkn, column_isin = identity.name, identity.wkn, identity.isin
  # Sparplan-Abrechnungen tragen die Wertpapieridentität in der Steuerzeile
  # "Stk. n NAME , WKN / ISIN: W / I"; die Seite-1-Tabelle kann defekt sein.
  line_match = TRADE_LINE.search(text)
  line_name = line_match.group("name").strip() if line_match else None
  line_wkn = line_match.group("wkn").upper() if line_match else None
  line_isin = line_match.group("isin").upper() if line_match and _valid_isin(line_match.group("isin")) else None
  identity_conflict = bool(column_isin and line_isin and column_isin != line_isin)
  if identity_conflict:
   identity = _SecurityIdentity(identity.name, identity.wkn, None, "AMBIGUOUS", "unterschiedliche ISINs im Dokument", identity.name_rows, identity.name_source)
  elif line_match and identity.status not in {"AMBIGUOUS", "INVALID"}:
   # Die Steuerzeile "Stk. n NAME , WKN / ISIN: W / I" ist bei
   # Sparplan-Abrechnungen vollständiger als ein defekter Tabellenkopf.
   column_wkn = line_wkn or column_wkn
   column_isin = line_isin or column_isin
   status = "RECOGNIZED" if column_isin else "PARTIAL" if (column_wkn or security_name) else "NOT_FOUND"
   identity = _SecurityIdentity(security_name, column_wkn, column_isin, status, IDENTITY_REASON.get(status, ""), identity.name_rows, identity.name_source)
  if line_name:
   security_name = line_name
  global_isins = [match.group(0).upper() for match in ISIN.finditer(text) if _valid_isin(match.group(0))]
  other_isins = {value for value in global_isins if value != column_isin and value != line_isin}
  if (column_isin or line_isin) and other_isins:
   identity = _SecurityIdentity(identity.name, identity.wkn or line_wkn, None, "AMBIGUOUS", "unterschiedliche ISINs im Dokument", identity.name_rows, identity.name_source)
  isin = None if other_isins or identity.status == "AMBIGUOUS" else (column_isin or line_isin)
  if not isin and identity.status in {"NOT_FOUND", "MISSING"} and len(set(global_isins)) == 1:
   isin = global_isins[0]
  depot_m=DEPOT.search(text); depot_id=None; depots=()
  if depot_m:
   number=re.sub(r"\s", "",depot_m.group(1)); de=ev("depot_number",depot_m); depot_id=stable_id("depot","comdirect",number)
   depots=(Depot(depot_id,bank_name=fv("comdirect",de),depot_number=fv(number,de),base_currency=fv("EUR",de),depot_type=FieldValue.manual(DepotType.WERTPAPIER)),)
  if d.handler_id=="kosteninformation_mifid_ii":
   cost_patterns=(("PRODUCT_COST",r"Produktkosten[^\n]*?("+A+r")\s*EUR"),("SERVICE_COST",r"Dienstleistungskosten[^\n]*?("+A+r")\s*EUR"),("ONE_OFF_COST",r"Einmalige Kosten[^\n]*?("+A+r")\s*EUR"),("ONGOING_COST",r"Laufende Kosten[^\n]*?("+A+r")\s*EUR"),("TRANSACTION_COST",r"Transaktionskosten[^\n]*?("+A+r")\s*EUR"),("INDUCEMENT",r"Zuwendungen[^\n]*?("+A+r")\s*EUR"))
   event_id=stable_id("event",doc.document_id,d.handler_id); info_type=CostInformationType.MIFID_EX_POST if re.search(r"ex[ -]?post",text,re.I) else CostInformationType.MIFID_EX_ANTE
   costs=[]
   for kind,pattern in cost_patterns:
    m=re.search(pattern,text,re.I)
    if m:
     ce=ev(kind.lower(),m); costs.append(CostEvent(stable_id("cost",event_id,kind),event_id,kind,dec(m.group(1)),"EUR",informational=True,evidence_ids=(ce,),information_type=info_type,document_id=doc.document_id,bank_id="comdirect",depot_id=depot_id,security_id=isin))
   if not costs:
    values=[dec(x) for x in re.findall(r"("+A+r")\s*EUR",text)]; costs=[CostEvent(stable_id("cost",event_id),event_id,"MIFID_DISCLOSURE",sum(values,Decimal()),"EUR",informational=True,evidence_ids=(eid,),information_type=info_type,document_id=doc.document_id,bank_id="comdirect",depot_id=depot_id,security_id=isin)]
   return self.result(doc,d,evidence,(FinancialEvent(event_id,doc.document_id,"MIFID_COST_INFORMATION",cost_events=tuple(costs),evidence_ids=(eid,)),),depots)
  if d.handler_id in {"vorabpauschale","investment_ausschuettung","dividende_steuer_inland"}:
   event_id=stable_id("event",doc.document_id,d.handler_id,isin); comps=tuple(TaxComponent(k,dec(m.group(1)),"EUR") for k,p in TAX for m in [re.search(p,text,re.I)] if m)
   advance=re.search(r"Vorabpauschale\s+EUR\s+("+A+r")",text,re.I); taxable=re.search(r"Steuerbemessungsgrundlage.*?EUR\s+("+A+r")",text,re.I|re.S); fsa=FSA_CONSUMPTION.search(text); stated_tax_year=TAX_YEAR.search(text)
   loss=re.search(r"Verlustverrechnung[^\n]*?EUR\s+("+A+r")",text,re.I); partial=re.search(r"Teilfreistellung\s+("+A+r")\s*%",text,re.I); accrual=re.search(r"(?:steuerlicher Zufluss|Zuflussdatum)\s*("+D+r")",text,re.I); booking=re.search(r"Buchungstag\s*("+D+r")",text,re.I)
   withheld=sum((x.amount for x in comps),Decimal())
   identity_name_excerpt=_original_excerpt(doc,(identity.name_source,*identity.name_rows,security_name)) if security_name else None
   identity_wkn_excerpt=_original_excerpt(doc,(column_wkn,)) if column_wkn else None
   identity_isin_excerpt=_original_excerpt(doc,(isin,)) if isin else None
   identity_issues=[]
   if security_name and not identity_name_excerpt:
    identity_issues.append(Issue(stable_id("issue",event_id,"security-name-evidence"),"COMDIRECT_SECURITY_NAME_UNVERIFIED",IssueSeverity.WARNING,
                                 "Wertpapiername im PDF-Text nicht belegbar; Name bleibt leer.",event_id=event_id,nature=IssueNature.MISSING_INFORMATION))
   if identity.status in {"AMBIGUOUS","INVALID"}:
    identity_issues.append(Issue(stable_id("issue",event_id,"security-identity",identity.status),"COMDIRECT_SECURITY_"+identity.status,IssueSeverity.WARNING,
                                 identity.reason or "Wertpapieridentität muss manuell geprüft werden.",event_id=event_id,nature=IssueNature.UNSECURED_ASSIGNMENT))
   accrual_evidence=ev("tax_accrual_date",accrual) if accrual else None
   tax_year_evidence=ev("tax_year",stated_tax_year) if stated_tax_year else ev("tax_year",accrual) if accrual else None
   consumption_evidence=ev("exemption_order_consumed",fsa) if fsa else None
   tax_year=int(stated_tax_year.group(1)) if stated_tax_year else date(accrual.group(1)).year if accrual else None
   tax=TaxEvent(
       stable_id("tax",event_id),event_id,"ADVANCE_TAX" if d.handler_id=="vorabpauschale" else d.handler_id,
       comps,evidence_ids=(eid,),depot_id=depot_id,isin=isin,bank_id="comdirect",tax_year=tax_year,
       tax_year_evidence_ids=(tax_year_evidence,) if tax_year_evidence else (),
       accrual_date=date(accrual.group(1)) if accrual else None,
       accrual_date_evidence_ids=(accrual_evidence,) if accrual_evidence else (),
       booking_date=date(booking.group(1)) if booking else MissingValue.NOT_FOUND,
       advance_before_partial_exemption=dec(advance.group(1)) if advance else MissingValue.NOT_FOUND,
       taxable_amount=dec(taxable.group(1)) if taxable else MissingValue.NOT_FOUND,
       exemption_order_used=dec(fsa.group(1)) if fsa else MissingValue.UNKNOWN,
       exemption_order_used_evidence_ids=(consumption_evidence,) if consumption_evidence else (),
       loss_offset_used=dec(loss.group(1)) if loss else MissingValue.UNKNOWN,
       partial_exemption_rate=dec(partial.group(1))/Decimal("100") if partial else MissingValue.UNKNOWN,
       actually_withheld_tax=withheld)
   identity_evidence=tuple(ev(field,excerpt)
                           for field,value,excerpt in (("security_name",security_name,identity_name_excerpt),
                                                       ("security_wkn",column_wkn,identity_wkn_excerpt),
                                                       ("security_isin",isin,identity_isin_excerpt)) if value and excerpt)
   events=(FinancialEvent(event_id,doc.document_id,"ADVANCE_TAX" if d.handler_id=="vorabpauschale" else "TAX_NOTICE",
                          tax_events=(tax,),evidence_ids=(eid,),
                          security_name=(security_name if identity_name_excerpt else MissingValue.NOT_FOUND),
                          security_wkn=column_wkn if identity_wkn_excerpt else MissingValue.NOT_FOUND,
                          security_isin=isin if identity_isin_excerpt else MissingValue.NOT_FOUND,
                          security_identity_evidence_ids=identity_evidence),)
   calculations=(); carryforwards=()
   if d.handler_id=="vorabpauschale":
    calculations=(AdvanceTaxCalculation(tax.tax_event_id,MissingValue.UNKNOWN,MissingValue.UNKNOWN,MissingValue.UNKNOWN,tax.advance_before_partial_exemption,tax.taxable_amount,withheld,comps,approval_status=TaxApprovalStatus.SYNTHETIC_ONLY),)
    if depot_id and isin and tax.tax_year and isinstance(tax.taxable_amount,Decimal): carryforwards=(AdvanceTaxCarryforward(stable_id("carryforward",tax.tax_event_id),tax.tax_event_id,depot_id,isin,tax.tax_year,tax.taxable_amount,(eid,)),)
   return self.result(doc,d,evidence,events,depots,issues=tuple(identity_issues),tax_calculations=calculations,tax_carryforwards=carryforwards)
  return self.transaction(doc,d,evidence,ev,fv,depots,depot_id,isin,eid,security_name,column_wkn,column_isin,identity)
 def transaction(self,doc,d,evidence,ev,fv,depots,depot_id,isin,eid,security_name=None,column_wkn=None,column_isin=None,identity=None):
  text=doc.text; h=d.handler_id; kind="BUY" if h=="wertpapierkauf" else "SELL" if h=="wertpapierverkauf" else "REDEMPTION" if h=="einloesung" else "DIVIDEND"
  reversal=DIVIDEND_REVERSAL.search(text) if kind=="DIVIDEND" else None
  if reversal:
   kind="REVERSAL"
  # Werte aus der "Steuerlichen Behandlung" sind nur Ersatz, wenn die Abrechnung selbst keinen Wert liefert.
  tax_section=re.search(r"Steuerliche\s*Behandlung",text); head=text[:tax_section.start()] if tax_section else text
  quantity_match=NENNWERT_QTY.search(head) or QTY.search(head) or QTY.search(text)
  qty=dec(quantity_match.group(1)) if quantity_match and dec(quantity_match.group(1))>0 else None
  line_match=TRADE_LINE.search(text)
  exec_match=TRADE_EXECUTION.search(head)
  cipher=None if exec_match else _cipher_trade(head,text[len(head):])
  if cipher: qty=cipher[0]
  if quantity_match is None and cipher is None and line_match is not None:
   candidate=dec(line_match.group("qty"))
   if candidate>0: qty=candidate
  if quantity_match is None and qty is None and exec_match is not None and exec_match.group("qty"):
   candidate=dec(exec_match.group("qty"))
   if candidate>0: qty=candidate
  settlement=SETTLE.search(text,reversal.end() if reversal else 0); valuta=VALUTA.search(text)
  column_date=_settlement_column_date(text) if valuta is None else None
  if reversal and settlement and (settlement.group("dir") or "").lower()!="lasten":
   settlement=None
  event_id=stable_id("event",doc.document_id,h,isin,settlement.group("a") if settlement else "")
  adjustment=LIQUIDATION_ADJUSTMENT.search(head) if kind=="REDEMPTION" else None
  issues=[]
  identity = identity or _SecurityIdentity()
  labelled_wkn = next((match.group(1).upper() for match in WKN.finditer(text)), None)
  if labelled_wkn and not re.fullmatch(r"[A-Z0-9]{6}", labelled_wkn):
   labelled_wkn = None
  resolved_wkn = column_wkn or labelled_wkn or (line_match.group("wkn").upper() if line_match else None)
  # Der Name stammt ggf. aus dem Layouttext (andere Spaltenfolge/Zeichenabstände);
  # als Evidence zählt nur Originaltext der Seiten, sonst bleibt der Name leer.
  name_excerpt=_original_excerpt(doc,(identity.name_source,*identity.name_rows,security_name)) if security_name else None
  if security_name and not name_excerpt:
   issues.append(Issue(stable_id("issue",event_id,"security-name-evidence"),"COMDIRECT_SECURITY_NAME_UNVERIFIED",IssueSeverity.WARNING,
                       "Wertpapiername im PDF-Text nicht belegbar; Name bleibt leer.",event_id=event_id,nature=IssueNature.MISSING_INFORMATION))
   security_name=None
  if identity.status in {"AMBIGUOUS", "INVALID"}:
   issues.append(Issue(stable_id("issue", event_id, "security-identity", identity.status),
                       "COMDIRECT_SECURITY_" + identity.status, IssueSeverity.WARNING,
                       identity.reason or "Wertpapieridentität muss manuell geprüft werden.",
                       event_id=event_id, nature=IssueNature.UNSECURED_ASSIGNMENT))
  for code,missing,message in (("COMDIRECT_SECURITY_MISSING",not (isin or resolved_wkn),"Wertpapieridentität fehlt."),("COMDIRECT_QUANTITY_MISSING",qty is None,"Stückzahl fehlt."),("COMDIRECT_SETTLEMENT_MISSING",settlement is None,"Settlementbetrag fehlt.")):
   if missing: issues.append(Issue(stable_id("issue",event_id,code),code,IssueSeverity.WARNING,message,event_id=event_id,nature=IssueNature.MISSING_INFORMATION))
  if kind in {"BUY","SELL","REDEMPTION"} and exec_match is None and cipher is None and CIPHER_TRADE.search(head) and not (PRICE.search(head) and MARKET_VALUE.search(head)):
   issues.append(Issue(stable_id("issue",event_id,"COMDIRECT_TRADE_VALUES_UNRESOLVED"),"COMDIRECT_TRADE_VALUES_UNRESOLVED",IssueSeverity.WARNING,
                       "Kurs und Kurswert stehen in einer defekten eingebetteten Schrift und sind nicht eindeutig entschlüsselbar; sie bleiben leer.",
                       event_id=event_id,nature=IssueNature.MISSING_INFORMATION))
  event_ev=ev("economic_event",settlement if settlement else re.search(next(p for x,p in TITLES if x==h),text,re.I|re.S)); iban=IBAN.search(text); account_id=None; accounts=()
  event_date=date(valuta.group(1)) if valuta else column_date[0] if column_date else None
  event_date_type="value_date" if valuta or column_date and column_date[1]=="value_date" else "booking_date" if column_date else MissingValue.UNKNOWN
  event_date_evidence=ev(event_date_type,valuta if valuta else column_date[2]) if valuta or column_date else None
  event_evidence=(event_ev,)+( (event_date_evidence,) if event_date_evidence else () )
  if reversal:
   reversal_ev=ev("dividend_reversal",reversal)
   event_evidence+=(reversal_ev,)
   issues.append(Issue(stable_id("issue",event_id,"dividend-reversal"),"COMDIRECT_DIVIDEND_REVERSAL_UNLINKED",
                       IssueSeverity.WARNING,"Dividendenstorno: Originalbuchung und gebuchten Endbetrag separat abgleichen.",
                       evidence_id=reversal_ev,event_id=event_id,nature=IssueNature.UNSECURED_ASSIGNMENT))
  if adjustment:
   adjustment_ev=ev("liquidation_adjustment",adjustment)
   event_evidence+=(adjustment_ev,)
   if quantity_match:
    event_evidence+=(ev("reference_holding_quantity",quantity_match),)
   issues.append(Issue(stable_id("issue",event_id,"liquidation-adjustment"),"COMDIRECT_LIQUIDATION_ADJUSTMENT_UNCONFIRMED",
                       IssueSeverity.WARNING,"Liquidationsnachzahlung: Der gebuchte Endbetrag ist separat zu belegen.",
                       evidence_id=adjustment_ev,event_id=event_id,nature=IssueNature.MISSING_INFORMATION))
  if iban:
   iban_value=re.sub(r"\s","",iban.group(0)); ie=ev("iban",iban); account_id=stable_id("account","comdirect",iban_value); accounts=(Account(account_id,bank_name=fv("comdirect",ie),iban=fv(iban_value,ie),currency=fv("EUR",ie)),)
  links=()
  if depot_id and account_id:
   links=(DepotAccountLink(stable_id("depot-account",depot_id,account_id,doc.document_id),depot_id,account_id,fv("SETTLEMENT",ie),valid_from=fv(date(valuta.group(1)),event_ev) if valuta else FieldValue.unknown(),is_default=FieldValue.manual(False)),)
  cash=()
  security=()
  if settlement:
    sign=-1 if kind=="BUY" or (settlement.group("dir") or "").lower()=="lasten" else 1
    cash_status=CashStatus.ACTUAL if account_id and not (adjustment or reversal) else CashStatus.EXPECTED
    movement_type=(CashMovementType.REVERSAL if reversal else CashMovementType.OTHER if adjustment else CashMovementType.SECURITY_BUY if kind=="BUY" else
                   CashMovementType.SECURITY_SELL if kind in {"SELL","REDEMPTION"} else CashMovementType.DIVIDEND_CREDIT)
    cash=(CashMovement(stable_id("cash",event_id),event_id,dec(settlement.group("a"))*sign,settlement.group("cur"),cash_status,
                       account_id=account_id,evidence_ids=event_evidence,movement_type=movement_type),)
  # A dividend credit carries identity but is not a purchase, sale or depot
  # position change.  Never synthesize a SecurityMovement for it.
  security=() if adjustment or kind not in {"BUY", "SELL", "REDEMPTION"} or not(qty and isin) else (SecurityMovement(stable_id("security",event_id),event_id,isin,qty if kind=="BUY" else -qty,(event_ev,),depot_id),)
  fees=tuple(FeeEvent(stable_id("fee",event_id,k),"trading",k,dec(m.group(1)),"EUR",date(valuta.group(1)) if valuta else date("01.01.1970"),FeeEffect.INCLUDED_IN_SETTLEMENT,doc.document_id,"comdirect",depot_id=depot_id,account_id=account_id,security_id=isin,transaction_id=event_id,evidence_ids=(event_ev,)) for k,p in FEE for m in [re.search(p,text,re.I)] if m)
  # Nur Käufe: dort ist die Belastung vor Steuern genau Kurswert plus Entgelte; Klartextgebühren haben Vorrang.
  if kind=="BUY" and cipher and not fees:
   fees=tuple(FeeEvent(stable_id("fee",event_id,k),"trading",k,amount,"EUR",date(valuta.group(1)) if valuta else date("01.01.1970"),FeeEffect.INCLUDED_IN_SETTLEMENT,doc.document_id,"comdirect",depot_id=depot_id,account_id=account_id,security_id=isin,transaction_id=event_id,evidence_ids=(event_ev,)) for k,amount in _cipher_fees(head,text[len(head):],cipher))
  # Die "Steuerliche Behandlung" eines Kaufs wirkt nur auf den Verrechnungstopf; ihre 0,00-Zeilen sind keine einbehaltene Steuer.
  comps=tuple(TaxComponent(k,dec(m.group(1)),"EUR") for k,p in TAX for m in [re.search(p,text,re.I)] if m and (kind!="BUY" or dec(m.group(1))>0))
  taxes=(TaxEvent(stable_id("tax",event_id),event_id,"REVERSAL_CORRECTION" if reversal else "WITHHOLDING",comps,evidence_ids=(event_ev,),depot_id=depot_id,isin=isin,bank_id="comdirect",account_id=account_id),) if comps else ()
  trades=()
  if not adjustment and kind in {"BUY","SELL","REDEMPTION"}:
   pm=PRICE.search(head); mm=MARKET_VALUE.search(head); gm=GROSS.search(head); fx=FX.search(head); nm=NAME.search(text); tm=TRADE_DATE.search(text); xm=EXECUTION_DATE.search(text); dm=TRADE_DAY.search(text)
   name_value=nm.group(1).strip() if nm else None
   if name_value and not re.sub(r"[/\s]|WPKNR|WKN|ISIN","",name_value,flags=re.I): name_value=None
   if not name_value: name_value=security_name
   price=dec(pm.group("a")) if pm else (dec(exec_match.group("price")) if exec_match else cipher[1] if cipher else None)
   market=dec(mm.group("a")) if mm else (dec(exec_match.group("market")) if exec_match else cipher[2] if cipher else None)
   trades=(SecurityTrade(stable_id("trade",event_id),event_id,kind,name_value or MissingValue.NOT_FOUND,isin or MissingValue.NOT_FOUND,resolved_wkn or MissingValue.NOT_FOUND,qty if qty is not None else MissingValue.NOT_FOUND,date(tm.group(1)) if tm else (date(dm.group(1)) if dm else MissingValue.NOT_FOUND),date(xm.group(1)) if xm else MissingValue.NOT_FOUND,date(valuta.group(1)) if valuta else column_date[0] if column_date and column_date[1]=="value_date" else MissingValue.NOT_FOUND,price if price is not None else MissingValue.NOT_FOUND,(pm.group("cur1") or pm.group("cur2")) if pm and (pm.group("cur1") or pm.group("cur2")) else ("EUR" if price is not None and not pm else MissingValue.NOT_FOUND),market if market is not None else MissingValue.NOT_FOUND,dec(gm.group("a")) if gm else MissingValue.NOT_FOUND,dec(fx.group(1)) if fx else MissingValue.NOT_FOUND,dec(settlement.group("a")) if settlement else MissingValue.NOT_FOUND,settlement.group("cur") if settlement else MissingValue.NOT_FOUND,depot_id,account_id,event_evidence,
                      booking_date=column_date[0] if column_date and column_date[1]=="booking_date" else MissingValue.UNKNOWN,
                      booking_date_evidence_ids=(event_date_evidence,) if column_date and column_date[1]=="booking_date" else ()),)
  identity_evidence=tuple(ev(label,name_excerpt if label=="security_name" else value)
                          for label,value in (("security_wkn",resolved_wkn),("security_isin",isin),("security_name",security_name)) if value)
  reference_matches=tuple(BANK_REFERENCE.finditer(text))
  reference_values=tuple(re.sub(r"\s+","",match.group(1)) for match in reference_matches)
  valid_references=tuple(value for value in reference_values if 8 <= len(value) <= 40)
  invalid_references=tuple(value for value in reference_values if not 8 <= len(value) <= 40)
  distinct_references=tuple(dict.fromkeys(valid_references))
  if len(distinct_references) > 1:
   reference=MissingValue.NOT_FOUND; reference_status="AMBIGUOUS"
  elif invalid_references:
   reference=MissingValue.NOT_FOUND; reference_status="INVALID"
  elif distinct_references:
   reference=distinct_references[0]; reference_status="RECOGNIZED"
  else:
   reference=MissingValue.UNKNOWN; reference_status="MISSING"
  reference_evidence=tuple(ev("bank_reference",match) for match in reference_matches)
  if reference_status in {"AMBIGUOUS", "INVALID"}:
   issues.append(Issue(stable_id("issue", event_id, "bank-reference", reference_status),
                       "COMDIRECT_BANK_REFERENCE_" + reference_status, IssueSeverity.WARNING,
                       "Bankreferenz ist nicht eindeutig bzw. formal ungültig.", event_id=event_id,
                       nature=IssueNature.UNSECURED_ASSIGNMENT))
  exchange_rates=()
  explicit_rates=tuple(EXPLICIT_FX_PAIR.finditer(text)) if kind in {"BUY","SELL","REDEMPTION"} else ()
  if len(explicit_rates)==1:
   rate_match=explicit_rates[0]
   base=rate_match.group("base").upper(); quote=rate_match.group("quote").upper()
   rate_evidence=ev("exchange_rate",rate_match)
   if base!=quote:
    exchange_rates=(ExchangeRate(stable_id("exchange-rate",event_id,base,quote,rate_match.group("rate")),event_id,
                                  dec(rate_match.group("rate")),base,quote,
                                  date(rate_match.group("date")) if rate_match.group("date") else MissingValue.UNKNOWN,
                                  MissingValue.UNKNOWN,(rate_evidence,)),)
   else:
    issues.append(Issue(stable_id("issue",event_id,"exchange-rate"),"COMDIRECT_EXCHANGE_RATE_INVALID",IssueSeverity.WARNING,
                        "Wechselkurs muss zwei verschiedene, ausdrücklich genannte Währungen enthalten.",rate_evidence,event_id,
                        IssueNature.MISSING_INFORMATION))
  elif len(explicit_rates)>1:
   rate_evidence=ev("exchange_rate_ambiguous","\n".join(match.group(0) for match in explicit_rates))
   issues.append(Issue(stable_id("issue",event_id,"exchange-rate-ambiguous"),"COMDIRECT_EXCHANGE_RATE_AMBIGUOUS",IssueSeverity.WARNING,
                       "Mehrere Wechselkurse im Beleg lassen sich diesem Vorgang nicht eindeutig zuordnen.",rate_evidence,event_id,
                       IssueNature.UNSECURED_ASSIGNMENT))
  event=FinancialEvent(event_id,doc.document_id,kind,event_date,cash,security,tax_events=taxes,fee_events=fees,evidence_ids=event_evidence,trades=trades,security_name=security_name or MissingValue.UNKNOWN,security_wkn=resolved_wkn or MissingValue.UNKNOWN,security_isin=isin or MissingValue.UNKNOWN,security_identity_evidence_ids=identity_evidence,bank_reference=reference,bank_reference_status=reference_status,bank_reference_evidence_ids=reference_evidence,
                       event_date_type=event_date_type,event_date_evidence_ids=(event_date_evidence,) if event_date_evidence else (),
                       exchange_rates=exchange_rates,reversal_details=_reversal_details(text,ev) if reversal else None); return self.result(doc,d,evidence,(event,),depots,accounts,tuple(issues),links)
 def result(self,doc,d,evidence,events,depots=(),accounts=(),issues=(),links=(),tax_calculations=(),tax_carryforwards=()): return ParsedDocument(stable_id("result",doc.document_id,self.metadata.version),doc.document_id,self.metadata.plugin_id,self.metadata.version,d.handler_id,events=events,evidence=tuple(evidence),issues=issues,depots=depots,accounts=accounts,depot_account_links=links,tax_calculations=tax_calculations,tax_carryforwards=tax_carryforwards)

FR_NAMES=("Girokonto","Tagesgeld PLUS-Konto","Tagesgeld PLUS","Tagesgeldkonto","Verrechnungskonto","O&F-Konto")
FR_ACCOUNT_LINE=re.compile(r"^("+"|".join(FR_NAMES)+r")\s+(DE(?:\s*\d){20})(?:\s+([+-]?"+A+r"))?(?:\s+([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?))?$")
# Historische Layouts nennen die IBANs je Konto nur im Hinweisblock "Für Ihre Überweisungen ...".
FR_LABELLED_IBAN=re.compile(r"^-?\s*(Girokonto|Tagesgeld PLUS(?:-Konto)?|Tagesgeldkonto|Verrechnungskonto|O&F-Konto)\s*:\s*Konto\s+\d+\s+IBAN\s+(DE(?:\s*\d){20})")
FR_HEADING=re.compile(r"^(Girokonto|Tagesgeld(?: PLUS(?:-Konto)?)?|Tagesgeldkonto|Verrechnungskonto|O&F-Konto)(?:\s+(?:Dispositionskredit|ec|girocard)(?=\b|EUR).*)?$")
FR_SECTION_PREAMBLE=re.compile(r"^(?:EUR(?:\s|$)|Umsätze EUR$|(?:Visa|ec|girocard)\s+Tages|Dispositionskredit(?:\b|EUR))")
FR_SALDO=re.compile(r"^(Alter|Neuer)\s+Saldo\s+("+D+r")(?:\s+([+-]?"+A+r"))?$",re.I)
FR_AMOUNT=re.compile(r"^[+-]?"+A+r"$")
FR_BOOKING_AMOUNT=re.compile(r"^[+-]"+A+r"$")
FR_BOOKING_AMOUNT_TAIL=re.compile(r"^(?P<purpose>.+?)\s+(?P<amount>[+-]"+A+r")$")
FR_BANK_BOOKING_REFERENCE=re.compile(r"^[A-Z0-9]{8,}/\d{1,8}$",re.I)
FR_SECURITY_LABEL=re.compile(r"^WPKNR:\s*(?P<wkn>[A-Z0-9]{6})(?:\s+ISIN:\s*(?P<isin>.*))?$",re.I)
FR_DATE_LINE=re.compile(r"^"+D+r"$")
FR_ROW=re.compile(r"^("+D+r")(?:\s+("+D+r"))?\s+(.*?)\s+([+-]"+A+r")$")
FR_ROW_TYPE_FIRST=re.compile(r"^(\D.*?)\s+("+D+r")\s+("+D+r")\s+([+-]"+A+r")$")
FR_DIRECT_DEBIT_REFERENCE=re.compile(
 r"^Lastschrift\s*/\s*Belastung\s*"
 r"((?:[A-Z0-9]{16}|[A-Z0-9]{12}\s+[A-Z0-9]{4}|[A-Z0-9]{11}\s+[A-Z0-9]{5})/[0-9]{1,8})(?=\s|$)"
)
FR_HISTORICAL_AMOUNT=re.compile(r"(?<!\d)([+-]"+A+r")(?!\d)")
FR_POSITION_HEAD=re.compile(r"^([A-Z0-9]{6})\s*/\s*(Girosammelverwahrung|Wertpapierrechnung)$")
FR_POSITION_VALUES=re.compile(r"^("+A+r")\s+("+A+r")(?:\s+([A-Z]{3}))?\s+("+A+r")$")
FR_POSITION_REST=re.compile(r"^([+-]?"+A+r")(?:\s+([+-]"+A+r"))?$")
FR_POSITION_ROW=re.compile(r"^([A-Z]{2}[A-Z0-9]{9}\d)\s+("+A+r")\s+("+A+r")\s+EUR\s+("+A+r")\s+EUR\s+("+D+r")$")
FR_CUSTOMER=re.compile(r"Kundennummer:?\s*\d{3}\s+(\d+)")
FR_INTEREST_HEAD=re.compile(r"AbschlussZinsenKto(\d+)EUR.*?von("+D+r")bis("+D+r").*?Habenzinsen",re.I)
FR_INTEREST_CLOSING=re.compile(r"Abschlussrechnung("+A+r")EUR",re.I)
FR_INTEREST_RATES=re.compile(r"(\d[\d.]*,\d{2,4})%ab(\d{2}\.\d{2}\.)("+A+r")EUR",re.I)
FR_ACCOUNT_NUMBER=re.compile(r"Ihre\s+Kontonummer:\s*(\d+)",re.I)
FR_BANK_CODE=re.compile(r"(?:Bankleitzahl|BLZ)\s*:?\s*([\d ]{8,})",re.I)
FR_HEADER_IBAN=re.compile(r"\bIBAN\s*:?\s*(DE(?:\s*\d){20})",re.I)
FR_REPORT_HEADER=re.compile(r"Finanzreport\s+Nr\.?\s*(\S+)",re.I)
FR_REPORT_DATE=re.compile(r"Finanzreport\s+Nr\.\s*\d+\s+(?:per|vom)\s+("+D+r")",re.I)
FR_SKIP_EXACT=frozenset({"Buchungstag","Valuta","Vorgang","Referenz","Auftraggeber/Empfänger","IBAN/BIC","Buchungstext Ausgang","Eingang","Kontoübersicht","Ihre aktuellen Salden IBAN Saldo in","EUR","WKN / Verwahrart","Bezeichnung","Anzahl / Nominal letzter","Kurs","Währung Kurswert","Stückzinsen","Kaufwert Gewinn /","Verlust","Depotbestand","Depotbestand EUR EUR","Zinsübersicht","Steuerübersicht","Wichtige Hinweise","Ihre Kontodaten IBAN BIC"})


def _comdirect_iban(bank_code, account_number):
 """Build a German IBAN from an evidenced comdirect bank/account number."""
 bank_code=re.sub(r"\s", "", bank_code or "")
 account_number=re.sub(r"\s", "", account_number or "")
 if not re.fullmatch(r"\d{8}", bank_code) or not re.fullmatch(r"\d{1,10}", account_number): return None
 # Beim siebenstelligen comdirect-Hauptkonto bilden achtstellige Stammnummer
 # und zweistellige Unterkontonummer (Giro = 00) die zehnstellige Kontonummer.
 if len(account_number)==7: account_number=account_number.zfill(8)+"00"
 else: account_number=account_number.zfill(10)
 bban=bank_code+account_number
 remainder=int(bban+"131400")%97  # DE00 -> D=13, E=14
 check_digits=98-remainder
 iban=f"DE{check_digits:02d}{bban}"
 return iban if int(bban+f"1314{check_digits:02d}")%97==1 else None


def _valid_german_iban(value):
 compact=re.sub(r"\s", "", value or "").upper()
 if not re.fullmatch(r"DE\d{20}", compact): return False
 rearranged=compact[4:]+compact[:4]
 digits="".join(str(ord(char)-55) if char.isalpha() else char for char in rearranged)
 return int(digits)%97==1


def _finanzreport_lines(document):
 """Significant compacted lines with their PDF page and offset in the joined text."""
 lines=[]; base=0
 for page in document.pages:
  for hit in re.finditer(r"[^\n]+",page.text):
   compact=" ".join(hit.group(0).split())
   if compact: lines.append((page.number,base+hit.start(),compact))
  base+=len(page.text)+1
 return lines


def _account_kind(name):
 lowered=name.lower()
 if "giro" in lowered: return AccountType.GIRO, AccountFunction.PAYMENT
 if "tagesgeld" in lowered: return AccountType.TAGESGELD, AccountFunction.SAVINGS
 return AccountType.OTHER, AccountFunction.SETTLEMENT


def _account_balance_evidence_id(account_balances, account_id):
 """Return one real balance source that locates an account-level reconciliation issue."""
 identifiers=[]
 for balance in account_balances:
  if balance.account_id==account_id:
   identifiers.extend(balance.amount.evidence_ids)
 return next(iter(dict.fromkeys(identifiers)),None)


def _parse_legacy_finanzreport(plugin, document, detection, lines, report_date, evidence, ev, fv):
 """Parse Finanzreports ohne IBAN im getrennten Tabellenlayout älterer PDFs."""
 text = document.text
 account_number_match = FR_ACCOUNT_NUMBER.search(text) or re.search(r"Kontonummer\s*:?\s*(\d+)\s*/\s*BLZ", text, re.I)
 account_number = account_number_match.group(1) if account_number_match else None
 bank_code_match=FR_BANK_CODE.search(text)
 bank_code=re.sub(r"\s", "", bank_code_match.group(1)) if bank_code_match else None
 header_iban_match=FR_HEADER_IBAN.search(text)
 header_iban=re.sub(r"\s", "", header_iban_match.group(1)).upper() if header_iban_match else None
 primary_iban=_comdirect_iban(bank_code,account_number) if bank_code and account_number else None
 if not account_number:
  return None
 heading_positions = []
 for index, (page, offset, line) in enumerate(lines):
  heading = FR_HEADING.match(line)
  if heading:
   tail=lines[index+1:index+15]
   name=heading.group(1)
   if any(item[2].startswith("Buchungstag") for item in tail) and name not in {item[3] for item in heading_positions}:
    heading_positions.append((index, page, offset, name))
 if not heading_positions:
  return None
 for section_index,(start_index,_page,_offset,_name) in enumerate(heading_positions):
  stop_index=heading_positions[section_index+1][0] if section_index+1<len(heading_positions) else len(lines)
  if any(IBAN.search(row[2]) for row in lines[start_index:stop_index]):
   return None
 if any(re.search(r"(?:Girokonto|Tagesgeld(?:\s+PLUS(?:-Konto)?)?|Tagesgeldkonto|Verrechnungskonto)\s+DE(?:\s*\d){20}", row[2], re.I) for row in lines):
  return None
 accounts=[]; balances=[]; events=[]; issues=[]; events_seen=set()
 account_ids={}
 for _index,page,offset,name in heading_positions:
  aid=stable_id("account","comdirect-legacy",account_number,name)
  if name in account_ids: continue
  account_ids[name]=aid
  section_end=next((heading[0] for heading in heading_positions if heading[0]>_index),len(lines))
  section_text="\n".join(item[2] for item in lines[_index:section_end])
  subaccount_match=FR_INTEREST_HEAD.search(re.sub(r"\s+", "", section_text))
  subaccount_number=subaccount_match.group(1) if subaccount_match else None
  account_iban=primary_iban if name=="Girokonto" else (_comdirect_iban(bank_code,subaccount_number) if bank_code and subaccount_number else None)
  if name=="Girokonto" and header_iban:
   if _valid_german_iban(header_iban) and account_iban==header_iban: account_iban=header_iban
   else:
    account_iban=None
    issues.append(Issue(stable_id("issue",aid,"iban-mismatch"),"ACCOUNT_IBAN_MISMATCH",IssueSeverity.ERROR,"Die IBAN im Reportkopf stimmt nicht mit der IBAN aus Kontonummer und BLZ überein.",nature=IssueNature.UNSECURED_ASSIGNMENT))
  account_ev=ev("account", f"{name} – Kontonummer {account_number}"+(f" / IBAN {account_iban}" if account_iban else ""), offset=offset)
  account_type,function=_account_kind(name)
  accounts.append(Account(aid,bank_name=fv("comdirect",account_ev),account_name=fv(name,account_ev),account_type=fv(account_type,account_ev),account_number=fv(subaccount_number or account_number,account_ev),iban=fv(account_iban,account_ev) if account_iban else FieldValue.unknown(),currency=fv("EUR",account_ev),functions=(FieldValue.manual(function),)))
 for section_index,(start_index,_page,_offset,name) in enumerate(heading_positions):
  if name not in account_ids: continue
  stop_index=heading_positions[section_index+1][0] if section_index+1<len(heading_positions) else len(lines)
  section=lines[start_index+1:stop_index]
  if not any(row[2].startswith("Buchungstag") or row[2].startswith("Umsätze") for row in section): continue
  aid=account_ids[name]; dates=[]; description=[]; pending_amount=None; pending_offset=None; pending_page=None; opening=None; closing=None
  def flush_booking():
   nonlocal pending_amount,dates,description,pending_offset,pending_page
   if pending_amount is not None and len(dates)==2:
    add_booking(str(pending_amount),pending_amount,dates,description,pending_offset,pending_page)
   elif len(dates)==2 and description:
    incomplete_excerpt="\n".join([*dates,*description])
    incomplete_ev=ev("incomplete_booking",incomplete_excerpt,offset=pending_offset)
    issues.append(Issue(stable_id("issue",aid,"legacy-incomplete",pending_offset),"INCOMPLETE_BOOKING",IssueSeverity.WARNING,"Historischer Buchungsblock ohne Betrag; Buchung wurde nicht übernommen.",incomplete_ev,nature=IssueNature.MISSING_INFORMATION))
   pending_amount=None; dates=[]; description=[]; pending_offset=None; pending_page=None
  def add_booking(amount_line, amount, booking_dates, body_lines, row_offset, row_page):
   if len(booking_dates)!=2:
    return
   booked=date(booking_dates[0]); valuta=date(booking_dates[1]); purpose=" ".join(body_lines).strip()
   key=(aid,booked,valuta,purpose,amount)
   if key in events_seen: return
   events_seen.add(key)
   event_id=stable_id("event",*key)
   excerpt="\n".join([*booking_dates,*body_lines,amount_line]).strip()
   evidence_id=ev("booking",excerpt,offset=row_offset)
   movement=CashMovement(stable_id("cash",event_id),event_id,amount,"EUR",CashStatus.ACTUAL,account_id=aid,evidence_ids=(evidence_id,),movement_type=CashMovementType.INTEREST_CREDIT if re.search(r"Zinsgutschrift|Habenzins|Kontoabschluss",purpose,re.I) else CashMovementType.OTHER)
   events.append(FinancialEvent(event_id,document.document_id,"CASH_BOOKING",booked,(movement,),evidence_ids=(evidence_id,)))
  cursor=0
  while cursor<len(section):
   page,offset,line=section[cursor]; cursor+=1
   if line in {"Umsätze","Umsätze EUR","Umsätze","EUR","Buchungstag","Buchungstag Valuta Soll / Haben","Valuta","Soll / Haben","Kto. / IBAN BLZ / BIC"}: continue
   saldo_inline=FR_SALDO.match(line)
   if line.startswith(("Alter Saldo","Neuer Saldo")):
    flush_booking()
    saldo_inline=saldo_inline or re.match(r"^(Alter|Neuer) Saldo(?:\s+("+D+r"))?\s+([+-]?"+A+r")$",line,re.I)
    value=saldo_inline.group(3) if saldo_inline and saldo_inline.lastindex>=3 else (saldo_inline.group(2) if saldo_inline else (section[cursor][2] if cursor<len(section) else ""))
    if FR_AMOUNT.fullmatch(value):
     amount=dec(value); kind="opening" if saldo_inline and saldo_inline.group(1).lower()=="alter" else "closing"
     balance_ev=ev(kind+"_balance",line+"\n"+value,offset=offset)
     balance_date=date(report_date) if report_date else None
     balances.append(AccountBalance(stable_id("balance",aid,kind,offset),aid,fv(balance_date,balance_ev) if balance_date else FieldValue.unknown(),fv(amount,balance_ev),fv("EUR",balance_ev),FieldValue.manual(kind)))
     if kind=="opening": opening=amount
     else: closing=amount
     if not saldo_inline: cursor+=1
    continue
   combined=FR_ROW.match(line)
   type_first=FR_ROW_TYPE_FIRST.match(line)
   if combined and combined.group(2):
    flush_booking()
    add_booking(line,dec(combined.group(4)),[combined.group(1),combined.group(2)],[combined.group(3)],offset,page)
    continue
   if type_first:
    flush_booking()
    add_booking(line,dec(type_first.group(4)),[type_first.group(2),type_first.group(3)],[type_first.group(1)],offset,page)
    continue
   if FR_DATE_LINE.fullmatch(line):
    if len(dates)==2:
     flush_booking()
    dates.append(line)
    continue
   amount_matches=list(FR_HISTORICAL_AMOUNT.finditer(line))
   if len(amount_matches)==1:
    amount_match=amount_matches[0]
    amount=dec(amount_match.group(1)); purpose=(line[:amount_match.start()]+" "+line[amount_match.end():]).strip()
    if len(dates)==2:
     pending_amount=amount; pending_offset=offset; pending_page=page
     if purpose: description.append(purpose)
    elif pending_amount is None:
     row_evidence=ev("historical_booking_layout",line,offset=offset)
     issues.append(Issue(stable_id("issue",aid,"legacy-booking",offset),"HISTORICAL_BOOKING_LAYOUT_UNSUPPORTED",IssueSeverity.ERROR,"Historischer Buchungsblock hat keine zwei eindeutigen Datumszeilen.",evidence_id=row_evidence,nature=IssueNature.MISSING_INFORMATION))
    continue
   if line in {"Kontoabschluss","Saldo nach Abschluss","Habenzinsen"} or line.startswith(("Abschluss Zinsen Kto","von ","Abschlussrechnung","0,250%","3,800%")):
    if pending_amount is not None and line.startswith("Abschluss Zinsen Kto"):
     flush_booking()
    continue
   if line.strip(): description.append(line)
  flush_booking()
  if opening is not None and closing is not None:
   total=sum((event.cash_movements[0].amount for event in events if event.cash_movements and event.cash_movements[0].account_id==aid and event.event_date is not None and report_date and event.event_date<=date(report_date)),Decimal())
   if opening+total!=closing:
    mismatch_evidence=_account_balance_evidence_id(balances,aid)
    issues.append(Issue(stable_id("issue",aid,"balance"),"BALANCE_MISMATCH",IssueSeverity.ERROR,"Anfangssaldo plus Buchungen entspricht nicht dem Endsaldo.",evidence_id=mismatch_evidence,nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
 return ParsedDocument(stable_id("result",document.document_id,plugin.metadata.version),document.document_id,plugin.metadata.plugin_id,plugin.metadata.version,detection.handler_id,events=tuple(events),evidence=tuple(evidence),issues=tuple(issues),attributes={"document_number":FR_REPORT_HEADER.search(text).group(1) if FR_REPORT_HEADER.search(text) else MissingValue.NOT_FOUND,"report_date":report_date or MissingValue.NOT_FOUND,"layout_path":"legacy"},accounts=tuple(accounts),account_balances=tuple(balances))


class ComdirectFinanzreportPlugin(ComdirectPlugin):
 metadata=next(x for x in APPROVED_PLUGINS if x.plugin_id=="comdirect.finanzreport")
 def detect(self,doc): return (Detection(self.metadata.plugin_id,self.metadata.version,"finanzreport","comdirect Finanzreport",Decimal("0.99"),"Finanzreport header recognized"),) if re.search("comdirect",doc.text,re.I) and re.search(r"Finanzreport\s+Nr",doc.text,re.I) else ()
 def parse(self,doc,d):
  text=doc.text; ev,fv,evidence=evidence_recorder(doc,self.metadata.plugin_id,d.handler_id,self.metadata.version)
  deferred_evidence=[]
  header=re.search(r"Finanzreport\s+Nr\.?\s*(\S*)",text,re.I); ev("document_type",header)
  period=re.search(r"(?:Berichtszeitraum|Zeitraum)\s*:?[ \t]*("+D+r")\s*(?:bis|-)\s*("+D+r")",text,re.I)
  report_dates={hit.group(1) for hit in FR_REPORT_DATE.finditer(text)}
  report_date=report_dates.pop() if len(report_dates)==1 else None
  lines=_finanzreport_lines(doc)
  legacy_result=_parse_legacy_finanzreport(self,doc,d,lines,report_date,evidence,ev,fv)
  if legacy_result is not None: return legacy_result
  issues=[]; accounts=[]; by_iban={}; names={}; overview={}; depot_expected=None
  events=[]; balances=[]; seen=set(); opened={}; closed={}; section_accounts=set()
  current=None; depot_mode=False; depot_done=False
  pending=None
  positions=[]; pos=None; depot_values=[]; depot_total_excerpt=None; depot_total_offset=None

  def account_dto(name,iban,bic,excerpt,offset):
   if iban in by_iban: return by_iban[iban]
   aid=stable_id("account","comdirect",iban); at,function=_account_kind(name)
   ie=ev("account",excerpt,offset=offset)
   extra={"bic":fv(bic,ie)} if bic else {}
   account=Account(aid,bank_name=fv("comdirect",ie),account_name=fv(name,ie),account_type=fv(at,ie),iban=fv(iban,ie),currency=fv("EUR",ie),functions=(FieldValue.manual(function),),**extra)
   accounts.append(account); by_iban[iban]=aid; names.setdefault(name.lower(),iban)
   return aid

  def flush_booking():
   nonlocal pending
   if pending is None: return
   block,pending=pending,None
   if block["amount"] is None:
    incomplete_evidence=ev("incomplete_booking","\n".join(block["raw"]),offset=block["offset"])
    issues.append(Issue(stable_id("issue",doc.document_id,"incomplete",block["offset"]),"INCOMPLETE_BOOKING",IssueSeverity.WARNING,"Buchungsblock ohne Betrag; Buchung wurde nicht übernommen.",incomplete_evidence,nature=IssueNature.MISSING_INFORMATION)); return
   purpose=" ".join(block["body"]); key=(current,block["booked"],block["valuta"] or "",purpose,block["amount"])
   event_id=stable_id("event",*key)
   if key in seen:
    duplicate_ev=ev("duplicate_booking","\n".join(block["raw"]),offset=block["offset"])
    issues.append(Issue(stable_id("issue",event_id,"duplicate"),"DUPLICATE_BOOKING",IssueSeverity.WARNING,"Duplicate booking in Finanzreport.",evidence_id=duplicate_ev,event_id=event_id,nature=IssueNature.CONFIRMED_DEVIATION)); return
   seen.add(key)
   excerpt="\n".join(block["raw"])
   if block.get("historical"):
    evidence_page_number=evidence_page(doc,excerpt,block["offset"])
    be=stable_id("evidence",doc.document_id,evidence_page_number,"booking",excerpt,event_id)
    deferred_evidence.append(Evidence(be,doc.document_id,evidence_page_number,"booking",excerpt,f"page:{evidence_page_number}",doc.source_hash,self.metadata.plugin_id,d.handler_id,self.metadata.version))
   else:
    be=ev("booking",excerpt,offset=block["offset"])
   interest=FR_INTEREST_HEAD.search(re.sub(r"\s+","",purpose))
   taxes=()
   if interest:
    comps=tuple(TaxComponent(k,dec(m.group(1)),"EUR") for k,p in TAX for m in [re.search(p,purpose,re.I)] if m)
    if comps:
     taxes=(TaxEvent(stable_id("tax",event_id),event_id,"WITHHOLDING",comps,evidence_ids=(be,),account_id=current,bank_id="comdirect"),)
    gross=sum((dec(m.group(3)) for m in FR_INTEREST_RATES.finditer(re.sub(r"\s+","",purpose))),Decimal())
    net=dec(FR_INTEREST_CLOSING.search(re.sub(r"\s+","",purpose)).group(1)) if FR_INTEREST_CLOSING.search(re.sub(r"\s+","",purpose)) else None
    withheld=sum((c.amount for c in comps),Decimal())
    if net is not None and abs(gross-withheld-net)>Decimal("0.01"):
     issues.append(Issue(stable_id("issue",event_id,"interest"),"INTEREST_RECONCILIATION",IssueSeverity.ERROR,"Zinsabschluss ist nicht abgestimmt (Brutto %.2f, Steuern %.2f, Netto %.2f)."%(gross,withheld,net),be,event_id,IssueNature.MATHEMATICAL_INCONSISTENCY))
   custody=bool(re.search(r"Verwahrentgelt",purpose,re.I)) and block["amount"]<0
   movement=CashMovement(stable_id("cash",event_id),event_id,block["amount"],"EUR",CashStatus.ACTUAL,account_id=current,evidence_ids=(be,),movement_type=CashMovementType.INTEREST_CREDIT if interest else CashMovementType.FEE_DEBIT if custody else CashMovementType.OTHER)
   # Eine vorhandene Kontobelastung ist die einzige Cash-Bewegung; FeeEvent ist mit ihr verknüpft.
   fees=(FeeEvent(stable_id("fee",event_id),"custody","verwahrentgelt",abs(block["amount"]),"EUR",date(block["booked"]),FeeEffect.ACTUAL_BOOKED,doc.document_id,"comdirect",account_id=current,transaction_id=event_id,cash_movement_id=movement.movement_id,evidence_ids=(be,)),) if custody else ()
   # Die Reportreferenz steht nach der Vorgangsart; nur das belegte enge
   # Kennungsmuster wird übernommen. SEPA-Referenzen bleiben davon getrennt.
   body_lines=block["body"]
   reference=FR_DIRECT_DEBIT_REFERENCE.match("\n".join(body_lines))
   reference_value=re.sub(r"\s+","",reference.group(1)) if reference else None
   reference_lines=[line for line in body_lines if FR_BANK_BOOKING_REFERENCE.fullmatch(re.sub(r"\s+","",line))]
   reference_line=reference_lines[0] if len(reference_lines)==1 else None
   if reference is None and reference_line is not None:
    reference_value=re.sub(r"\s+","",reference_line)
   body_rows=block.get("body_rows",())
   def body_offset(line):
    return next((row_offset for row_line,row_offset in body_rows if row_line==line),block["offset"])
   reference_evidence=ev("bank_reference",reference_line,offset=body_offset(reference_line)) if reference_line else be if reference else None
   security_name=MissingValue.UNKNOWN; security_wkn=MissingValue.UNKNOWN; security_isin=MissingValue.UNKNOWN
   identity_evidence=[]
   invalid_reference_evidence=None
   marker_index=next((i for i,line in enumerate(body_lines) if line.casefold()=="wertpapiere"),None)
   label_index=next((i for i,line in enumerate(body_lines) if FR_SECURITY_LABEL.match(line)),None)
   if marker_index is not None and marker_index+1<len(body_lines):
    likely_reference=body_lines[marker_index+1].strip()
    if ("/" in likely_reference and not FR_BANK_BOOKING_REFERENCE.fullmatch(re.sub(r"\s+","",likely_reference))
        and not likely_reference.casefold().startswith(("wkn", "wpknr", "isin"))):
     invalid_reference_evidence=ev("bank_reference_invalid",likely_reference,offset=body_offset(body_lines[marker_index+1]))
     issues.append(Issue(stable_id("issue",event_id,"reference-invalid"),"COMDIRECT_BANK_REFERENCE_INVALID",IssueSeverity.WARNING,"Mögliche Buchungsreferenz im Finanzreport hat ein nicht eindeutiges Format.",invalid_reference_evidence,event_id,IssueNature.UNSECURED_ASSIGNMENT))
   if marker_index is not None and label_index is not None and label_index>marker_index:
    label=FR_SECURITY_LABEL.match(body_lines[label_index]); wkn=label.group("wkn").upper()
    name_lines=[line.strip() for line in body_lines[marker_index+1:label_index]
                if line.strip() and not FR_BANK_BOOKING_REFERENCE.fullmatch(re.sub(r"\s+","",line))
                and not ("/" in line and line.strip()==(body_lines[marker_index+1].strip() if marker_index+1<len(body_lines) else ""))]
    if name_lines:
     security_name=" ".join(name_lines)
     identity_evidence.append(ev("security_identity_name","\n".join(name_lines),offset=body_offset(name_lines[0])))
    identity_evidence.append(ev("security_wkn",body_lines[label_index],offset=body_offset(body_lines[label_index])))
    security_wkn=wkn
    isin_text=label.group("isin") or ""
    isin_line_index=label_index
    if not isin_text.strip() and label_index+1<len(body_lines):
     isin_text=body_lines[label_index+1]
     isin_line_index=label_index+1
    isin_match=ISIN_CANDIDATE.search(isin_text.upper())
    if isin_match and _valid_isin(isin_match.group(0)):
     security_isin=isin_match.group(0).upper()
     identity_evidence.append(ev("security_isin",body_lines[isin_line_index],offset=body_offset(body_lines[isin_line_index])))
    elif isin_text.strip():
     invalid_ev=ev("security_isin_invalid",body_lines[isin_line_index],offset=body_offset(body_lines[isin_line_index]))
     issues.append(Issue(stable_id("issue",event_id,"security-isin"),"COMDIRECT_SECURITY_ISIN_INVALID",IssueSeverity.WARNING,"ISIN im Finanzreport ist ungültig und wurde nicht übernommen.",invalid_ev,event_id,IssueNature.MISSING_INFORMATION))
   status="MISSING"
   if len(reference_lines)>1:
    status="AMBIGUOUS"; reference_value=None
    ref_ev=ev("bank_reference_ambiguous","\n".join(reference_lines),offset=body_offset(reference_lines[0]))
    issues.append(Issue(stable_id("issue",event_id,"reference"),"COMDIRECT_BANK_REFERENCE_AMBIGUOUS",IssueSeverity.WARNING,"Mehrere mögliche Buchungsreferenzen im Finanzreport.",ref_ev,event_id,IssueNature.UNSECURED_ASSIGNMENT))
    reference_evidence=ref_ev
   elif reference_value:
    status="RECOGNIZED"
   else:
    labelled_ref=re.search(r"(?:Referenz|Buchungsreferenz)\s*:\s*([^\n]+)","\n".join(body_lines),re.I)
    if invalid_reference_evidence:
     status="INVALID"; reference_value=None; reference_evidence=invalid_reference_evidence
    elif labelled_ref:
     status="INVALID"
     ref_ev=ev("bank_reference_invalid",labelled_ref.group(0),offset=body_offset(labelled_ref.group(0)))
     issues.append(Issue(stable_id("issue",event_id,"reference"),"COMDIRECT_BANK_REFERENCE_INVALID",IssueSeverity.WARNING,"Buchungsreferenz im Finanzreport hat ein nicht unterstütztes Format.",ref_ev,event_id,IssueNature.UNSECURED_ASSIGNMENT))
     reference_evidence=ref_ev
   events.append(FinancialEvent(event_id,doc.document_id,"CASH_BOOKING",date(block["booked"]),(movement,),tax_events=taxes,fee_events=fees,evidence_ids=(be,),
                                security_name=security_name,security_wkn=security_wkn,security_isin=security_isin,
                                security_identity_evidence_ids=tuple(identity_evidence),
                                bank_reference=reference_value or MissingValue.UNKNOWN,bank_reference_status=status,
                                bank_reference_evidence_ids=(reference_evidence,) if reference_evidence else ()))
  def flush_position():
   nonlocal pos
   if pos is None: return
   block,pos=pos,None
   if block["value"] is None:
    raise ValueError("Finanzreport: Depotposition ohne Kurswertzeile: "+block["wkn"])
   if not block["name"] and block["require_name"]:
    raise ValueError("Finanzreport: Wertpapiername fehlt: "+block["wkn"])
   if re.search(r"(?:^|\s|[·|])(?:Vorgang|Verwendungszweck)\s*:",block["name"] or "",re.I):
    raise ValueError("Finanzreport: Buchungstext als Wertpapiername erkannt: "+block["wkn"])
   rest=[dec(value) for value in block["rest"]]
   if len(rest)>=3: block["cost"],block["profit"]=rest[1],rest[2]
   elif len(rest)==2: block["cost"],block["profit"]=rest[0],rest[1]
   elif len(rest)==1: block["cost"]=rest[0]
   if block["cost"] is not None and block["profit"] is not None and abs(block["value"]-block["cost"]-block["profit"])>Decimal("0.02"):
    issues.append(Issue(stable_id("issue",doc.document_id,"position",block["wkn"]),"DEPOT_POSITION_MISMATCH",IssueSeverity.ERROR,"Kurswert, Kaufwert und Gewinn/Verlust der Position %s sind nicht abgestimmt."%block["wkn"],nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
   positions.append(block)

  # Namensbezogene IBANs aus dem historischen Hinweisblock; widersprüchliche Angaben gelten als nicht eindeutig.
  labelled={}; labelled_conflicts=set(); historical_sections=set(); historical_incomplete=set(); historical_incomplete_evidence={}; historical_unassigned=set(); historical_modes={}; historical_pending=None; historical_leading_dates=[]; historical_leading_body=[]; historical_unanchored=[]
  for _page,label_offset,label_line in lines:
   label=FR_LABELLED_IBAN.match(label_line)
   if not label: continue
   label_name=label.group(1).lower(); label_iban=re.sub(r"\s","",label.group(2))
   if label_name in labelled and labelled[label_name][0]!=label_iban: labelled_conflicts.add(label_name)
   labelled.setdefault(label_name,(label_iban,label_line,label_offset))
  for label_name in labelled_conflicts: del labelled[label_name]

  def flush_historical():
   nonlocal historical_pending,pending
   if historical_pending is None: return
   block,historical_pending=historical_pending,None
   if len(block["dates"])!=2 or not block["body"]:
    historical_incomplete.add(block["account"]); return
   pending={"booked":block["dates"][0],"valuta":block["dates"][1],"body":block["body"],"raw":block["raw"],"amount":block["amount"],"offset":block["offset"],"page":block["page"],"historical":True}
   flush_booking()

  index=0
  while index<len(lines):
   page,offset,line=lines[index]
   index+=1
   if line.startswith(("Finanzreport ","Kundennummer","comdirect","25449 Quickborn","USt-ID:","Gesamtsaldo","Depotgesamtwert ","Die Kaufwerte")) or line in FR_SKIP_EXACT:
    continue
   if line=="Depot":
    following=lines[index][2] if index<len(lines) else ""
    match=re.fullmatch(r"Depot\s+([+-]?"+A+r")",line)
    if match: depot_expected=dec(match.group(1)); continue
    if FR_AMOUNT.fullmatch(following): depot_expected=dec(following); index+=1; continue
    flush_booking(); current=None; depot_mode=True; depot_done=False; continue
   account=FR_ACCOUNT_LINE.match(line)
   if account:
    name,iban=account.group(1),re.sub(r"\s","",account.group(2))
    aid=account_dto(name,iban,account.group(4),line,offset)
    flush_historical(); historical_leading_dates.clear(); historical_leading_body.clear(); historical_unanchored.clear(); flush_booking(); current=aid; depot_mode=False
    if account.group(3): overview[iban]=dec(account.group(3))
    elif index<len(lines) and FR_AMOUNT.fullmatch(lines[index][2]) and not FR_SALDO.match(lines[index][2]):
     overview[iban]=dec(lines[index][2]); index+=1
    continue
   heading=FR_HEADING.match(line)
   if heading:
    if heading.group(1)=="Tagesgeld" and index<len(lines) and lines[index][2].startswith("PLUS-Konto"):
     line="Tagesgeld "+lines[index][2]; index+=1; heading=FR_HEADING.match(line)
    table_start=index
    while table_start<len(lines) and FR_SECTION_PREAMBLE.match(lines[table_start][2]):
     table_start+=1
    if table_start<len(lines) and lines[table_start][2].startswith(("Buchungstag","Alter Saldo")):
     name=heading.group(1)
     iban=names.get(name.lower())
     if iban is None and name in {"Tagesgeld PLUS","Tagesgeld PLUS-Konto"}:
      iban=names.get("tagesgeld plus-konto" if name=="Tagesgeld PLUS" else "tagesgeld plus")
     if iban is None:
      found=labelled.get(name.lower()) or (labelled.get("tagesgeld plus-konto") if name.lower()=="tagesgeld plus" else None) or (labelled.get("tagesgeld plus") if name.lower()=="tagesgeld plus-konto" else None)
      if found is not None:
       account_dto(name,found[0],None,found[1],found[2]); iban=found[0]
     if iban is None:
      # Keine IBAN im Dokument bzw. nicht eindeutig: Bereich nicht zuordnen, Verlust sichtbar melden.
      flush_historical(); historical_leading_dates.clear(); historical_leading_body.clear(); historical_unanchored.clear()
      flush_booking(); flush_position(); current=None; depot_mode=False; depot_done=False
      lost=0
      for _p,_o,later in lines[table_start:]:
       if later.startswith("Neuer Saldo") or FR_HEADING.match(later) or FR_ACCOUNT_LINE.match(later): break
       if (FR_ROW.match(later) and not FR_DATE_LINE.fullmatch(later)) or FR_ROW_TYPE_FIRST.match(later): lost+=1
      reason="mehrdeutig" if name.lower() in labelled_conflicts else "im Dokument nicht vorhanden"
      account_issue_evidence=ev("account_iban_unresolved",line,offset=offset)
      issues.append(Issue(stable_id("issue",doc.document_id,"account-iban-missing",name.lower(),offset),"ACCOUNT_IBAN_UNRESOLVED",IssueSeverity.ERROR if lost else IssueSeverity.WARNING,"Kontobereich %s ohne eindeutige IBAN (%s); %d Buchung(en) wurden nicht übernommen."%(heading.group(1),reason,lost),evidence_id=account_issue_evidence,nature=IssueNature.UNSECURED_ASSIGNMENT))
      continue
     flush_historical(); historical_leading_dates.clear(); historical_leading_body.clear(); historical_unanchored.clear(); flush_booking(); flush_position(); current=by_iban[iban]; section_accounts.add(current); depot_mode=False; depot_done=False
     continue
   if depot_mode:
    if depot_done: continue
    if line.startswith(("Jahresdepotabstimmung","Stückzinsen gesamt","Gesamtwert","Gesamtkurswert")):
     flush_position()
     if line.startswith("Gesamtkurswert"):
      depot_total_excerpt=[line]; depot_total_offset=offset
      while index<len(lines) and (FR_AMOUNT.fullmatch(lines[index][2]) or lines[index][2] in FR_SKIP_EXACT or lines[index][2].startswith(("Stückzinsen gesamt","Gesamtwert"))):
       if FR_AMOUNT.fullmatch(lines[index][2]): depot_values.append(dec(lines[index][2]))
       elif not lines[index][2].startswith(("Stückzinsen gesamt","Gesamtwert")): depot_total_excerpt.append(lines[index][2])
       index+=1
     depot_done=True; continue
    if " über " in line and "AKV" in line: continue
    head=FR_POSITION_HEAD.match(line)
    if head:
     flush_position(); pos={"wkn":head.group(1),"custody_type":head.group(2),"page":page,"offset":offset,"raw":[line],"rows":[(line,offset)],"name":"","quantity":None,"price":None,"price_currency":None,"value":None,"cost":None,"profit":None,"rest":[],"require_name":True}; continue
    if pos is not None:
     values=FR_POSITION_VALUES.match(line)
     if values and pos["value"] is None:
      pos.update(quantity=dec(values.group(1)),price=dec(values.group(2)),price_currency=values.group(3),value=dec(values.group(4))); pos["raw"].append(line); pos["rows"].append((line,offset)); continue
     rest=FR_POSITION_REST.match(line)
     if rest and pos["value"] is not None:
      pos["rest"].extend(value for value in rest.groups() if value); pos["raw"].append(line); pos["rows"].append((line,offset)); continue
     if pos["value"] is None:
      if re.match(r"^[A-Z0-9]{6}(?: /| \d[\d.]*,)",line):
       raise ValueError("Finanzreport: nicht unterstützte Depotposition: "+line)
      pos["name"]=(pos["name"]+" "+line).strip(); pos["raw"].append(line); pos["rows"].append((line,offset)); continue
     continue
    row=FR_POSITION_ROW.match(line)
    if row:
     flush_position()
     pos={"wkn":row.group(1),"custody_type":None,"page":page,"offset":offset,"raw":[line],"rows":[(line,offset)],"name":None,"quantity":dec(row.group(2)),"price":dec(row.group(3)),"price_currency":"EUR","value":dec(row.group(4)),"cost":None,"profit":None,"rest":[],"require_name":False,"price_date":row.group(5)}
     flush_position(); continue
    continue
   row=FR_POSITION_ROW.match(line)
   if row and not depot_mode and current is None:
    flush_booking(); flush_position()
    pos={"wkn":row.group(1),"custody_type":None,"page":page,"offset":offset,"raw":[line],"rows":[(line,offset)],"name":None,"quantity":dec(row.group(2)),"price":dec(row.group(3)),"price_currency":"EUR","value":dec(row.group(4)),"cost":None,"profit":None,"rest":[],"require_name":False,"price_date":row.group(5)}
    flush_position(); continue
   if current is None: continue
   if line.startswith("Kto. / IBAN"):
    historical_sections.add(current); historical_unanchored.clear(); continue
   saldo=FR_SALDO.match(line)
   if saldo:
    flush_historical()
    if historical_unanchored: historical_unassigned.add(current); historical_unanchored.clear()
    if historical_leading_dates or historical_leading_body: historical_incomplete.add(current); historical_leading_dates.clear(); historical_leading_body.clear()
    flush_booking()
    amount=saldo.group(3); excerpt=line
    if amount is None and index<len(lines) and FR_AMOUNT.fullmatch(lines[index][2]):
     amount=lines[index][2]; excerpt=line+" "+amount; index+=1
    if amount is None:
     saldo_evidence=ev("saldo_amount_missing",line,offset=offset)
     issues.append(Issue(stable_id("issue",current,"saldo",saldo.group(2)),"SALDO_AMOUNT_MISSING",IssueSeverity.WARNING,"Saldo ohne Betrag; Saldenprüfung entfällt.",evidence_id=saldo_evidence,nature=IssueNature.MISSING_INFORMATION)); continue
    se=ev(("opening_balance" if saldo.group(1)=="Alter" else "closing_balance"),excerpt,offset=offset)
    balances.append(AccountBalance(stable_id("balance",current,saldo.group(1).lower(),saldo.group(2)),current,fv(date(saldo.group(2)),se),fv(dec(amount),se),fv("EUR",se),FieldValue.manual("opening" if saldo.group(1)=="Alter" else "closing")))
    (opened if saldo.group(1)=="Alter" else closed)[current]=dec(amount)
    if saldo.group(1)=="Neuer": current=None
    continue
   if current in historical_sections:
    amounts=list(FR_HISTORICAL_AMOUNT.finditer(line))
    if len(amounts)==1:
     if historical_unanchored: historical_unassigned.add(current); historical_unanchored.clear()
     mode=historical_modes.get(current)
     if historical_pending is not None:
      if mode=="amount-first" and len(historical_pending["dates"])>=2: flush_historical()
      else: historical_pending["body"].append(line); historical_pending["raw"].append(line); continue
     if mode is None:
      if len(historical_leading_dates)==2: mode="dates-first"
      elif not historical_leading_dates: mode="amount-first"
      else: historical_incomplete.add(current); historical_leading_dates.clear(); historical_leading_body.clear(); continue
      historical_modes[current]=mode
     if mode=="dates-first" and len(historical_leading_dates)!=2:
      historical_unassigned.add(current); historical_leading_dates.clear(); historical_leading_body.clear(); continue
     amount=amounts[0]; purpose=(line[:amount.start()]+" "+line[amount.end():]).strip()
     historical_pending={"account":current,"dates":list(historical_leading_dates),"body":[*historical_leading_body,purpose],"raw":[*historical_leading_dates,*historical_leading_body,line],"amount":dec(amount.group(1)),"offset":offset,"page":page}
     historical_leading_dates.clear(); historical_leading_body.clear()
     continue
    if FR_DATE_LINE.fullmatch(line):
     if historical_unanchored: historical_unassigned.add(current); historical_unanchored.clear()
     mode=historical_modes.get(current)
     if (len(historical_leading_dates)==2 and historical_leading_body and
         index<len(lines) and FR_DATE_LINE.fullmatch(lines[index][2])):
      incomplete_excerpt="\n".join([*historical_leading_dates,*historical_leading_body])
      incomplete_ev=ev("incomplete_booking",incomplete_excerpt)
      issues.append(Issue(stable_id("issue",current,"historical-incomplete",incomplete_ev),"INCOMPLETE_BOOKING",IssueSeverity.WARNING,"Historischer Buchungsblock ohne Betrag; Buchung wurde nicht übernommen.",incomplete_ev,nature=IssueNature.MISSING_INFORMATION))
      historical_incomplete_evidence[current]=incomplete_ev
      historical_incomplete.add(current)
      historical_leading_dates.clear(); historical_leading_body.clear()
     if mode=="dates-first":
      if historical_pending is not None: flush_historical()
      historical_leading_dates.append(line)
      if len(historical_leading_dates)>2: historical_incomplete.add(current)
     elif historical_pending is None:
      historical_leading_dates.append(line)
      if len(historical_leading_dates)>2: historical_incomplete.add(current)
     else:
      historical_pending["dates"].append(line); historical_pending["raw"].append(line)
     continue
    if historical_pending is None and historical_leading_dates: historical_leading_body.append(line)
    elif historical_pending is None: historical_unanchored.append(line)
    else: historical_pending["body"].append(line); historical_pending["raw"].append(line)
    continue
   row=FR_ROW.match(line)
   if row and not FR_DATE_LINE.fullmatch(line):
    flush_booking()
    pending={"booked":row.group(1),"valuta":row.group(2),"body":[row.group(3)],"body_rows":[(row.group(3),offset)],"raw":[line],"amount":dec(row.group(4)),"offset":offset,"page":page}
    flush_booking(); continue
   row=FR_ROW_TYPE_FIRST.match(line)
   if row:
    # Historisches Layout: Vorgangsart zuerst, danach Buchungstag, Valuta und Betrag.
    flush_booking()
    pending={"booked":row.group(2),"valuta":row.group(3),"body":[row.group(1)],"body_rows":[(row.group(1),offset)],"raw":[line],"amount":dec(row.group(4)),"offset":offset,"page":page}
    flush_booking(); continue
   if FR_DATE_LINE.fullmatch(line):
    if pending is None or pending["amount"] is not None:
     flush_booking(); pending={"booked":line,"valuta":None,"body":[],"body_rows":[],"raw":[line],"amount":None,"offset":offset,"page":page}
    elif pending["valuta"] is None and not pending["body"]:
     pending["valuta"]=line; pending["raw"].append(line)
    elif pending["valuta"] is not None and pending["body"] and index<len(lines) and FR_DATE_LINE.fullmatch(lines[index][2]):
     # Zwei Datumszeilen nach einem bereits begonnenen Zwecktext sind der
     # nächste Buchungsblock. Den alten unvollständigen Block nicht vermischen.
     flush_booking()
     pending={"booked":line,"valuta":None,"body":[],"body_rows":[],"raw":[line],"amount":None,"offset":offset,"page":page}
    else:
     pending["body"].append(line); pending["body_rows"].append((line,offset)); pending["raw"].append(line)
    continue
   if FR_BOOKING_AMOUNT.fullmatch(line) and pending is not None and pending["amount"] is None:
    pending["amount"]=dec(line); pending["raw"].append(line); flush_booking(); continue
   tail_amount=FR_BOOKING_AMOUNT_TAIL.fullmatch(line)
   if tail_amount and pending is not None and pending["amount"] is None and pending["valuta"] is not None:
    purpose_text=tail_amount.group("purpose").strip()
    if purpose_text:
     pending["body"].append(purpose_text); pending["body_rows"].append((line,offset))
    pending["amount"]=dec(tail_amount.group("amount")); pending["raw"].append(line); flush_booking(); continue
   if pending is not None:
    pending["body"].append(line); pending["body_rows"].append((line,offset)); pending["raw"].append(line)
  flush_historical(); flush_booking(); flush_position()

  unsupported_historical=set()
  for aid in sorted(historical_sections):
   account_events=[event for event in events if event.cash_movements and event.cash_movements[0].account_id==aid]
   total=sum((event.cash_movements[0].amount for event in account_events),Decimal())
   complete=aid not in historical_incomplete and aid not in historical_unassigned and aid in opened and aid in closed and opened[aid]+total==closed[aid]
   if complete: continue
   unsupported_historical.add(aid)
   reasons=[]
   if aid in historical_incomplete: reasons.append("unvollständiger oder mehrdeutiger Buchungsblock")
   if aid in historical_unassigned: reasons.append("nicht zuordenbare Tabellenzeile")
   if aid not in opened or aid not in closed: reasons.append("Anfangs- oder Endsaldo fehlt")
   elif opened[aid]+total!=closed[aid]: reasons.append("Saldenabweichung")
   report_ev=_account_balance_evidence_id(balances,aid)
   if not report_ev:
    report_ev=historical_incomplete_evidence.get(aid)
   issues.append(Issue(stable_id("issue",doc.document_id,"historical-bookings",aid),"HISTORICAL_BOOKING_LAYOUT_UNSUPPORTED",IssueSeverity.ERROR,"Historisches Buchungslayout nicht vollständig erkannt (%s); %d erkannte Buchungskandidaten wurden wegen des fehlenden Saldenabgleichs nicht als Kontobewegungen ausgegeben."%(", ".join(reasons),len(account_events)),evidence_id=report_ev,nature=IssueNature.MISSING_INFORMATION))
  if unsupported_historical:
   events=[event for event in events if not event.cash_movements or event.cash_movements[0].account_id not in unsupported_historical]
  for aid in (section_accounts|{event.cash_movements[0].account_id for event in events if event.cash_movements and event.cash_movements[0].account_id})-unsupported_historical:
   total=sum((event.cash_movements[0].amount for event in events if event.cash_movements and event.cash_movements[0].account_id==aid),Decimal())
   if aid not in opened or aid not in closed:
    account=next((item for item in accounts if item.account_id==aid),None)
    saldo_evidence=(account.iban.evidence_ids[0] if account and account.iban.evidence_ids else None)
    issues.append(Issue(stable_id("issue",aid,"saldo-missing"),"SALDO_MISSING",IssueSeverity.WARNING,"Anfangs- oder Endsaldo fehlt; Saldenprüfung entfällt.",evidence_id=saldo_evidence,nature=IssueNature.MISSING_INFORMATION)); continue
   if opened[aid]+total!=closed[aid]:
    mismatch_evidence=_account_balance_evidence_id(balances,aid)
    issues.append(Issue(stable_id("issue",aid,"balance"),"BALANCE_MISMATCH",IssueSeverity.ERROR,"Finanzreport balance is inconsistent.",evidence_id=mismatch_evidence,nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
   iban=next((key for key,value in by_iban.items() if value==aid),None)
   if iban is not None and iban in overview and overview[iban]!=closed[aid]:
    account=next((item for item in accounts if item.account_id==aid),None)
    overview_evidence=(account.iban.evidence_ids[0] if account and account.iban.evidence_ids else None)
    issues.append(Issue(stable_id("issue",aid,"overview"),"OVERVIEW_BALANCE_MISMATCH",IssueSeverity.ERROR,"Kontoübersicht und Endsaldo widersprechen sich.",evidence_id=overview_evidence,nature=IssueNature.MATHEMATICAL_INCONSISTENCY))

  depots=[]; snapshots=[]
  if positions or depot_expected is not None:
   depot_m=DEPOT.search(text); customer=FR_CUSTOMER.search(text)
   if depot_m: number,depot_excerpt=depot_m.group(1),depot_m
   elif customer: number,depot_excerpt=customer.group(1),customer
   else: raise ValueError("Finanzreport: Depotzuordnung ohne Depot- oder Kundennummer.")
   number=re.sub(r"\s","",number); de=ev("depot_number",depot_excerpt); did=stable_id("depot","comdirect",number)
   depots.append(Depot(did,bank_name=fv("comdirect",de),depot_number=fv(number,de),base_currency=fv("EUR",de),depot_type=FieldValue.manual(DepotType.WERTPAPIER)))
   if positions:
    position_dates=[block["price_date"] for block in positions if block.get("price_date")]
    if report_date is None and not position_dates:
     raise ValueError("Finanzreport: eindeutiger Stichtag fehlt.")
    asof=date(report_date) if report_date is not None else date(max(position_dates))
    report_ev=ev("report_date",FR_REPORT_DATE.search(text)) if report_date is not None else None
    snapshot_date_ev=report_ev
    if snapshot_date_ev is None and position_dates:
     latest_row=next((row_text,row_offset) for block in positions for row_text,row_offset in block.get("rows",())
                     if (match:=FR_POSITION_ROW.match(row_text)) and match.group(5)==max(position_dates))
     snapshot_date_ev=ev("snapshot_as_of",latest_row[0],offset=latest_row[1])
    te=None; total_value=FieldValue.unknown()
    if depot_values:
     te=ev("depot_total","\n".join(depot_total_excerpt or ["Gesamtkurswert"]),offset=depot_total_offset)
     total_value=fv(depot_values[0],te)
    elif (total:=re.search(r"Depotgesamtwert\s+("+A+r")\s+EUR",text,re.I)):
     te=ev("depot_total",total); total_value=fv(dec(total.group(1)),te)
    dto_positions=[]
    for block in positions:
     position_rows=block.get("rows",((block["raw"][0],block["offset"]),))
     row_for=lambda predicate: next(((row_text,row_offset) for row_text,row_offset in position_rows if predicate(row_text)),position_rows[0])
     security_row=position_rows[0]
     values_row=row_for(lambda value: bool(FR_POSITION_VALUES.match(value)) or bool(FR_POSITION_ROW.match(value)))
     name_rows=[(row_text,row_offset) for row_text,row_offset in position_rows[1:] if block["name"] and row_text in block["name"]]
     security_ev=ev("depot_position_security_id",security_row[0],offset=security_row[1])
     custody_ev=ev("depot_position_custody_type",security_row[0],offset=security_row[1]) if block.get("custody_type") else None
     quantity_ev=ev("depot_position_quantity",values_row[0],offset=values_row[1])
     market_value_ev=ev("depot_position_market_value",values_row[0],offset=values_row[1])
     currency_ev=ev("depot_position_currency",values_row[0],offset=values_row[1])
     price_ev=ev("depot_position_price",values_row[0],offset=values_row[1])
     name_ev=ev("depot_position_name","\n".join(row_text for row_text,_ in name_rows),offset=name_rows[0][1]) if name_rows else None
     price_date=date(block.get("price_date") or (report_date if report_date is not None else max(position_dates)))
     # Der Kurswert ist laut Spaltenkopf in EUR. Ohne Kurswährung ist nur ein
     # expliziter Nullkurs in der gemeinsamen Währungseinheit darstellbar.
     price,price_currency=block["price"],block["price_currency"]
     price_field=fv(price,price_ev) if price_currency=="EUR" or (price_currency is None and price==0) else FieldValue.unknown()
     price_date_ev=ev("depot_position_price_date",next((row_text for row_text,_ in position_rows if FR_POSITION_ROW.match(row_text)),position_rows[0][0]),offset=next((row_offset for row_text,row_offset in position_rows if FR_POSITION_ROW.match(row_text)),position_rows[0][1])) if block.get("price_date") else snapshot_date_ev
     dto_positions.append(DepotPosition(stable_id("position",did,block["wkn"]),fv(block["wkn"],security_ev),fv(block["quantity"],quantity_ev),security_name=fv(block["name"],name_ev) if block["name"] and name_ev else FieldValue.unknown(),market_value=fv(block["value"],market_value_ev),currency=fv("EUR",currency_ev),price=price_field,price_date=fv(price_date,price_date_ev) if price_date_ev else FieldValue.unknown(),custody_type=fv(block["custody_type"],custody_ev) if custody_ev else FieldValue.unknown()))
    snapshots.append(DepotSnapshot(stable_id("snapshot",did,asof,doc.document_id),did,fv(asof,snapshot_date_ev) if snapshot_date_ev else FieldValue.unknown(),tuple(dto_positions),total_value,fv("EUR",te) if te else FieldValue.unknown()))
    reported=depot_values[0] if depot_values else (dec(total.group(1)) if (total:=re.search(r"Depotgesamtwert\s+("+A+r")\s+EUR",text,re.I)) else None)
    if reported is not None:
     calculated=sum((block["value"] for block in positions),Decimal())
     if calculated!=reported:
      issues.append(Issue(stable_id("issue",did,"total"),"DEPOT_TOTAL_MISMATCH",IssueSeverity.ERROR,"Depot position sum differs from total.",te,nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
     if depot_expected is not None and reported!=depot_expected:
      issues.append(Issue(stable_id("issue",did,"expected"),"DEPOT_OVERVIEW_MISMATCH",IssueSeverity.ERROR,"Kontoübersicht und Depotgesamtwert widersprechen sich.",te,nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
  links=[]; seen_links=set()
  if depots and accounts:
   for match in re.finditer(r"(?:Abrechnungs|Verrechnungs|Settlement)konto\s*:?[ \t]*(DE(?:\s*\d){20})",text,re.I):
    iban=re.sub(r"\s","",match.group(1)); account=next((x for x in accounts if x.iban.value==iban),None)
    if account:
     link_key=(depots[0].depot_id,account.account_id)
     if link_key in seen_links: continue
     seen_links.add(link_key)
     le=ev("depot_account_link",match); links.append(DepotAccountLink(stable_id("depot-account",depots[0].depot_id,account.account_id,doc.document_id),depots[0].depot_id,account.account_id,fv("SETTLEMENT",le),valid_from=fv(date(period.group(1)),le) if period else FieldValue.unknown(),is_default=FieldValue.manual(False)))
  attrs={"document_number":header.group(1) or MissingValue.NOT_FOUND,"period_start":period.group(1) if period else MissingValue.NOT_FOUND,"period_end":period.group(2) if period else MissingValue.NOT_FOUND,"report_date":report_date or MissingValue.NOT_FOUND,"layout_path":"core" if re.search(r"IBAN|Depotgesamtwert",text,re.I) else "legacy"}
  return ParsedDocument(stable_id("result",doc.document_id,self.metadata.version),doc.document_id,self.metadata.plugin_id,self.metadata.version,"finanzreport",events=tuple(events),evidence=tuple(evidence+deferred_evidence),issues=tuple(issues),attributes=attrs,accounts=tuple(accounts),account_balances=tuple(balances),depots=tuple(depots),depot_snapshots=tuple(snapshots),depot_account_links=tuple(links))
