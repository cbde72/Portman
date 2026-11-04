"""Independent comdirect handlers; no V09 compatibility layer."""
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from itertools import product
import re
from portman_parsers.api import *
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
IDENTITY_ROW_PREFIX=re.compile(r"^\s*(?:per\s+\d{2}\.\d{2}\.\d{4}|(?:STK|Stk)\.?\s*-?\s*[\d.,]+)\s*",re.I)
IDENTITY_REASON={"PARTIAL":"nur WKN oder Name erkannt","AMBIGUOUS":"mehrere Kennungen im selben Wertpapierblock","INVALID":"ISIN-Prüfziffer oder ISIN-Format ungültig"}
QTY=re.compile(r"(?:Stk\.?|STK)\s*("+A+r")",re.I); NENNWERT_QTY=re.compile(r"Nennwert\s*Zum\s*(?:Misch)?Kurs\s*von\s*(?:St\.?|Stk\.?)\s*("+A+r")",re.I); VALUTA=re.compile(r"(?:Valuta|zahlbar\s+ab)\s*("+D+r")",re.I)
WKN=re.compile(r"\bWKN\s*:?[ \t]*([A-Z0-9]{6})\b",re.I)
BANK_REFERENCE=re.compile(r"\bReferenz(?:\s*[- ]?\s*(?:Nr\.?|nummer))?\s*:?\s*([A-Z0-9][A-Z0-9\s]*?)(?=\s*(?:Referenz|Depotnummer|Depotnr|Kundennummer|comdirect)|[^A-Z0-9\s]|\n\s*\n|$)",re.I)
TRADE_LINE=re.compile(r"Stk\.?\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s+(?P<name>.+?)\s*,?\s*WKN\s*/\s*ISIN\s*:\s*(?P<wkn>[A-Z0-9]{6})\s*/\s*(?P<isin>[A-Z]{2}[A-Z0-9]{9}\d)",re.I)
TRADE_EXECUTION=re.compile(r"Nennwert\s*Zum\s*(?:Misch)?Kurs\s*von\s*(?:St\.\s*(?P<qty>\d[\d.]*(?:,\d+)?)\s*)?EUR\s*(?P<price>\d[\d.]*(?:,\d+)?)\s*Kurswert\s*:?\s*EUR\s*(?P<market>"+A+r")",re.I)
TRADE_DAY=re.compile(r"(?:Wertpapierkauf|Wertpapierverkauf|Gesch\.ftsvorgang)\s*Nr\.?\s*\d+\s*vom\s*("+D+r")",re.I)
TRADE_DATE=re.compile(r"(?:Geschäftstag|Schlusstag)\s*:?[ \t]*("+D+r")",re.I)
EXECUTION_DATE=re.compile(r"(?:Ausführungstag|Ausführung)\s*:?[ \t]*("+D+r")",re.I)
PRICE=re.compile(r"(?:Ausführungskurs|Kurs)\s*:?[ \t]*(?:(?P<cur1>[A-Z]{3})\s*)?(?P<a>"+A+r")(?:\s*(?P<cur2>[A-Z]{3}))?",re.I)
MARKET_VALUE=re.compile(r"(?:Kurswert|Gegenwert)\s*:?[ \t]*(?P<cur>[A-Z]{3})\s*(?P<a>"+A+r")",re.I)
GROSS=re.compile(r"(?:Bruttobetrag|Bruttoertrag|Bruttodividende)\s*:?[ \t]*(?P<cur>[A-Z]{3})\s*(?P<a>"+A+r")",re.I)
FX=re.compile(r"(?:Devisenkurs|Umrechnungskurs)\s*:?[ \t]*("+A+r")",re.I)
NAME=re.compile(r"(?:Wertpapierbezeichnung|Bezeichnung)\s*:?[ \t]*(.+)",re.I)
SETTLE=re.compile(r"(?:Zu\s*Ihren\s*(?P<dir>Lasten|Gunsten)|(?:^|\n)Gutschrift|(?:^|\n)Zahlungsbetrag).{0,80}?(?P<cur>[A-Z]{3})\s*-?\s*(?P<a>"+A+r")",re.I|re.S)
TAX=(("CAPITAL_GAINS_TAX",r"Kapitalertragsteuer\s*(?:EUR)?\s*-?("+A+r")"),("SOLIDARITY_SURCHARGE",r"Solidarit.tszuschlag\s*(?:EUR)?\s*-?("+A+r")"),("CHURCH_TAX",r"Kirchensteuer\s*(?:EUR)?\s*-?("+A+r")"),("WITHHOLDING_TAX",r"Quellensteuer\s*(?:[A-Z]{3})?\s*-?("+A+r")"))
FEE=(("provision",r"Provision\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("foreign_expenses",r"(?:Fremdspesen|fremde\s+Spesen)\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("settlement_fee",r"Abwickl\.?\s*entgelt\s*Clearstream\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("exchange_fee",r"(?:B.rsenplatz.*Entgelt|B.rsengeb.hr)\s*:?\s*(?:EUR)?\s*-?("+A+r")"))
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
  if len(solutions)!=1: return None
  qty,price,market,trial=solutions[0]
  return qty,price,market,_cipher_fee(head,trade["sp"] if "sp" in trade.groupdict() else None,trial,market,settle)


def _cipher_fee(head,sp,key,market,settle):
  """Entschlüsselt die Provision mit dem Dokumentschlüssel; gilt nur bei eindeutiger Lösung.

  Fehlende Ziffern werden über die Sortierung des Schlüssels eingegrenzt. Die Lösung muss
  mit der gedruckten Belastung (Kurswert + Provision) übereinstimmen; sonst bleibt die Gebühr leer.
  """
  if not sp: return None
  row=re.search(r"Provision(?:"+re.escape(sp)+r")+\S"+re.escape(sp)+r"\SUR(?:"+re.escape(sp)+r")+(?P<fee>(?:(?!"+re.escape(sp)+r")\S)+)",head)
  if not row or not settle: return None
  coded=row["fee"]; known={int(p):c for c,p in key.items() if p.isdigit()}; comma=next((c for c,p in key.items() if p==","),None)
  unknown=sorted({c for c in coded if c not in key})
  def candidates(code):
    return [str(d) for d in range(10) if d not in known
            and all(c<code for k,c in known.items() if k<d) and all(c>code for k,c in known.items() if k>d)]
  if len(unknown)>2: return None
  found=set()
  for digits in product(*(candidates(code) for code in unknown)):
    if len(set(digits))<len(digits): continue
    trial={**key,**dict(zip(unknown,digits))}
    text="".join(trial[c] for c in coded)
    if not NUMBER_TEXT.fullmatch(text) or (comma and coded.count(comma)>1): continue
    fee=dec(text)
    if fee>0 and market+fee==dec(settle.group(1)): found.add(fee)
  return found.pop() if len(found)==1 else None


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
   advance=re.search(r"Vorabpauschale\s+EUR\s+("+A+r")",text,re.I); taxable=re.search(r"Steuerbemessungsgrundlage.*?EUR\s+("+A+r")",text,re.I|re.S); fsa=re.search(r"Freistellungsauftrag\s+EUR\s+("+A+r")",text,re.I)
   loss=re.search(r"Verlustverrechnung[^\n]*?EUR\s+("+A+r")",text,re.I); partial=re.search(r"Teilfreistellung\s+("+A+r")\s*%",text,re.I); accrual=re.search(r"(?:steuerlicher Zufluss|Zuflussdatum)\s*("+D+r")",text,re.I); booking=re.search(r"Buchungstag\s*("+D+r")",text,re.I)
   withheld=sum((x.amount for x in comps),Decimal())
   tax=TaxEvent(stable_id("tax",event_id),event_id,"ADVANCE_TAX" if d.handler_id=="vorabpauschale" else d.handler_id,comps,evidence_ids=(eid,),depot_id=depot_id,isin=isin,bank_id="comdirect",tax_year=date(accrual.group(1)).year if accrual else None,accrual_date=date(accrual.group(1)) if accrual else None,booking_date=date(booking.group(1)) if booking else MissingValue.NOT_FOUND,advance_before_partial_exemption=dec(advance.group(1)) if advance else MissingValue.NOT_FOUND,taxable_amount=dec(taxable.group(1)) if taxable else MissingValue.NOT_FOUND,exemption_order_used=dec(fsa.group(1)) if fsa else MissingValue.UNKNOWN,loss_offset_used=dec(loss.group(1)) if loss else MissingValue.UNKNOWN,partial_exemption_rate=dec(partial.group(1))/Decimal("100") if partial else MissingValue.UNKNOWN,actually_withheld_tax=withheld)
   events=(FinancialEvent(event_id,doc.document_id,"ADVANCE_TAX" if d.handler_id=="vorabpauschale" else "TAX_NOTICE",tax_events=(tax,),evidence_ids=(eid,)),)
   calculations=(); carryforwards=()
   if d.handler_id=="vorabpauschale":
    calculations=(AdvanceTaxCalculation(tax.tax_event_id,MissingValue.UNKNOWN,MissingValue.UNKNOWN,MissingValue.UNKNOWN,tax.advance_before_partial_exemption,tax.taxable_amount,withheld,comps,approval_status=TaxApprovalStatus.SYNTHETIC_ONLY),)
    if depot_id and isin and tax.tax_year and isinstance(tax.taxable_amount,Decimal): carryforwards=(AdvanceTaxCarryforward(stable_id("carryforward",tax.tax_event_id),tax.tax_event_id,depot_id,isin,tax.tax_year,tax.taxable_amount,(eid,)),)
   return self.result(doc,d,evidence,events,depots,tax_calculations=calculations,tax_carryforwards=carryforwards)
  return self.transaction(doc,d,evidence,ev,fv,depots,depot_id,isin,eid,security_name,column_wkn,column_isin,identity)
 def transaction(self,doc,d,evidence,ev,fv,depots,depot_id,isin,eid,security_name=None,column_wkn=None,column_isin=None,identity=None):
  text=doc.text; h=d.handler_id; kind="BUY" if h=="wertpapierkauf" else "SELL" if h=="wertpapierverkauf" else "REDEMPTION" if h=="einloesung" else "DIVIDEND"
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
  settlement=SETTLE.search(text); valuta=VALUTA.search(text); event_id=stable_id("event",doc.document_id,h,isin,settlement.group("a") if settlement else "")
  issues=[]
  identity = identity or _SecurityIdentity()
  labelled_wkn = next((match.group(1).upper() for match in WKN.finditer(text)), None)
  if labelled_wkn and not re.fullmatch(r"[A-Z0-9]{6}", labelled_wkn):
   labelled_wkn = None
  resolved_wkn = column_wkn or labelled_wkn or (line_match.group("wkn").upper() if line_match else None)
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
  if iban:
   iban_value=re.sub(r"\s","",iban.group(0)); ie=ev("iban",iban); account_id=stable_id("account","comdirect",iban_value); accounts=(Account(account_id,bank_name=fv("comdirect",ie),iban=fv(iban_value,ie),currency=fv("EUR",ie)),)
  links=()
  if depot_id and account_id:
   links=(DepotAccountLink(stable_id("depot-account",depot_id,account_id,doc.document_id),depot_id,account_id,fv("SETTLEMENT",ie),valid_from=fv(date(valuta.group(1)),event_ev) if valuta else FieldValue.unknown(),is_default=FieldValue.manual(False)),)
  cash=()
  security=()
  if settlement:
    sign=-1 if kind=="BUY" or (settlement.group("dir") or "").lower()=="lasten" else 1; cash=(CashMovement(stable_id("cash",event_id),event_id,dec(settlement.group("a"))*sign,settlement.group("cur"),CashStatus.ACTUAL if account_id else CashStatus.EXPECTED,account_id=account_id,evidence_ids=(event_ev,),movement_type=CashMovementType.SECURITY_BUY if kind=="BUY" else CashMovementType.SECURITY_SELL if kind in {"SELL","REDEMPTION"} else CashMovementType.DIVIDEND_CREDIT),)
  # A dividend credit carries identity but is not a purchase, sale or depot
  # position change.  Never synthesize a SecurityMovement for it.
  security=() if kind not in {"BUY", "SELL", "REDEMPTION"} or not(qty and isin) else (SecurityMovement(stable_id("security",event_id),event_id,isin,qty if kind=="BUY" else -qty,(event_ev,),depot_id),)
  fees=tuple(FeeEvent(stable_id("fee",event_id,k),"trading",k,dec(m.group(1)),"EUR",date(valuta.group(1)) if valuta else date("01.01.1970"),FeeEffect.INCLUDED_IN_SETTLEMENT,doc.document_id,"comdirect",depot_id=depot_id,account_id=account_id,security_id=isin,transaction_id=event_id,evidence_ids=(event_ev,)) for k,p in FEE for m in [re.search(p,text,re.I)] if m)
  # Provision in defekter eingebetteter Schrift: mit dem Dokumentschlüssel entschlüsselt (nur bei eindeutiger, zur Belastung passender Lösung).
  if cipher and cipher[3] is not None and not any(f.subcategory=="provision" for f in fees):
   fees+=(FeeEvent(stable_id("fee",event_id,"provision"),"trading","provision",cipher[3],"EUR",date(valuta.group(1)) if valuta else date("01.01.1970"),FeeEffect.INCLUDED_IN_SETTLEMENT,doc.document_id,"comdirect",depot_id=depot_id,account_id=account_id,security_id=isin,transaction_id=event_id,evidence_ids=(event_ev,)),)
  elif kind in {"BUY","SELL"} and cipher and cipher[3] is None and "Provision" in head and not any(f.subcategory=="provision" for f in fees):
   issues.append(Issue(stable_id("issue",event_id,"COMDIRECT_FEE_UNRESOLVED"),"COMDIRECT_FEE_UNRESOLVED",IssueSeverity.WARNING,"Die Provision steht in einer defekten eingebetteten Schrift und ist nicht eindeutig entschlüsselbar; sie bleibt leer.",event_id=event_id,nature=IssueNature.MISSING_INFORMATION))
  # Die "Steuerliche Behandlung" eines Kaufs wirkt nur auf den Verrechnungstopf; ihre 0,00-Zeilen sind keine einbehaltene Steuer.
  comps=tuple(TaxComponent(k,dec(m.group(1)),"EUR") for k,p in TAX for m in [re.search(p,text,re.I)] if m and (kind!="BUY" or dec(m.group(1))>0)); taxes=(TaxEvent(stable_id("tax",event_id),event_id,"WITHHOLDING",comps,evidence_ids=(event_ev,),depot_id=depot_id,isin=isin,bank_id="comdirect",account_id=account_id),) if comps else ()
  trades=()
  if kind in {"BUY","SELL","REDEMPTION"}:
   pm=PRICE.search(head); mm=MARKET_VALUE.search(head); gm=GROSS.search(head); fx=FX.search(head); nm=NAME.search(text); tm=TRADE_DATE.search(text); xm=EXECUTION_DATE.search(text); dm=TRADE_DAY.search(text)
   name_value=nm.group(1).strip() if nm else None
   if name_value and not re.sub(r"[/\s]|WPKNR|WKN|ISIN","",name_value,flags=re.I): name_value=None
   if not name_value: name_value=security_name
   price=dec(pm.group("a")) if pm else (dec(exec_match.group("price")) if exec_match else cipher[1] if cipher else None)
   market=dec(mm.group("a")) if mm else (dec(exec_match.group("market")) if exec_match else cipher[2] if cipher else None)
   trades=(SecurityTrade(stable_id("trade",event_id),event_id,kind,name_value or MissingValue.NOT_FOUND,isin or MissingValue.NOT_FOUND,resolved_wkn or MissingValue.NOT_FOUND,qty if qty is not None else MissingValue.NOT_FOUND,date(tm.group(1)) if tm else (date(dm.group(1)) if dm else MissingValue.NOT_FOUND),date(xm.group(1)) if xm else MissingValue.NOT_FOUND,date(valuta.group(1)) if valuta else MissingValue.NOT_FOUND,price if price is not None else MissingValue.NOT_FOUND,(pm.group("cur1") or pm.group("cur2")) if pm and (pm.group("cur1") or pm.group("cur2")) else ("EUR" if price is not None and not pm else MissingValue.NOT_FOUND),market if market is not None else MissingValue.NOT_FOUND,dec(gm.group("a")) if gm else MissingValue.NOT_FOUND,dec(fx.group(1)) if fx else MissingValue.NOT_FOUND,dec(settlement.group("a")) if settlement else MissingValue.NOT_FOUND,settlement.group("cur") if settlement else MissingValue.NOT_FOUND,depot_id,account_id,(event_ev,)),)
  identity_evidence=tuple(ev(label,(identity.name_source or value) if label=="security_name" else value,
                             *(identity.name_rows if label=="security_name" else ()))
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
  event=FinancialEvent(event_id,doc.document_id,kind,date(valuta.group(1)) if valuta else None,cash,security,tax_events=taxes,fee_events=fees,evidence_ids=(event_ev,),trades=trades,security_name=security_name or MissingValue.UNKNOWN,security_wkn=resolved_wkn or MissingValue.UNKNOWN,security_isin=isin or MissingValue.UNKNOWN,security_identity_evidence_ids=identity_evidence,bank_reference=reference,bank_reference_status=reference_status,bank_reference_evidence_ids=reference_evidence); return self.result(doc,d,evidence,(event,),depots,accounts,tuple(issues),links)
 def result(self,doc,d,evidence,events,depots=(),accounts=(),issues=(),links=(),tax_calculations=(),tax_carryforwards=()): return ParsedDocument(stable_id("result",doc.document_id,self.metadata.version),doc.document_id,self.metadata.plugin_id,self.metadata.version,d.handler_id,events=events,evidence=tuple(evidence),issues=issues,depots=depots,accounts=accounts,depot_account_links=links,tax_calculations=tax_calculations,tax_carryforwards=tax_carryforwards)

FR_NAMES=("Girokonto","Tagesgeld PLUS-Konto","Tagesgeld PLUS","Tagesgeldkonto","Verrechnungskonto","O&F-Konto")
FR_ACCOUNT_LINE=re.compile(r"^("+"|".join(FR_NAMES)+r")\s+(DE(?:\s*\d){20})(?:\s+([+-]?"+A+r"))?(?:\s+([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?))?$")
FR_HEADING=re.compile(r"^(Girokonto|Tagesgeld(?: PLUS(?:-Konto)?)?|Tagesgeldkonto|Verrechnungskonto|O&F-Konto)(?:\s+(?:Dispositionskredit|ec|girocard)\b.*)?$")
FR_SALDO=re.compile(r"^(Alter|Neuer)\s+Saldo\s+("+D+r")(?:\s+([+-]?"+A+r"))?$",re.I)
FR_AMOUNT=re.compile(r"^[+-]?"+A+r"$")
FR_BOOKING_AMOUNT=re.compile(r"^[+-]"+A+r"$")
FR_DATE_LINE=re.compile(r"^"+D+r"$")
FR_ROW=re.compile(r"^("+D+r")(?:\s+("+D+r"))?\s+(.*?)\s+([+-]"+A+r")$")
FR_POSITION_HEAD=re.compile(r"^([A-Z0-9]{6})\s*/\s*(Girosammelverwahrung|Wertpapierrechnung)$")
FR_POSITION_VALUES=re.compile(r"^("+A+r")\s+("+A+r")\s+([A-Z]{3})\s+("+A+r")$")
FR_POSITION_REST=re.compile(r"^([+-]?"+A+r")(?:\s+([+-]"+A+r"))?$")
FR_POSITION_ROW=re.compile(r"^([A-Z]{2}[A-Z0-9]{9}\d)\s+("+A+r")\s+("+A+r")\s+EUR\s+("+A+r")\s+EUR\s+("+D+r")$")
FR_CUSTOMER=re.compile(r"Kundennummer:?\s*\d{3}\s+(\d+)")
FR_INTEREST_HEAD=re.compile(r"AbschlussZinsenKto(\d+)EUR.*?von("+D+r")bis("+D+r").*?Habenzinsen",re.I)
FR_INTEREST_CLOSING=re.compile(r"Abschlussrechnung("+A+r")EUR",re.I)
FR_INTEREST_RATES=re.compile(r"(\d[\d.]*,\d{2,4})%ab(\d{2}\.\d{2}\.)("+A+r")EUR",re.I)
FR_REPORT_DATE=re.compile(r"Finanzreport\s+Nr\.\s*\d+\s+(?:per|vom)\s+("+D+r")",re.I)
FR_SKIP_EXACT=frozenset({"Buchungstag","Valuta","Vorgang","Referenz","Auftraggeber/Empfänger","IBAN/BIC","Buchungstext Ausgang","Eingang","Kontoübersicht","Ihre aktuellen Salden IBAN Saldo in","EUR","WKN / Verwahrart","Bezeichnung","Anzahl / Nominal letzter","Kurs","Währung Kurswert","Stückzinsen","Kaufwert Gewinn /","Verlust","Depotbestand","Depotbestand EUR EUR","Zinsübersicht","Steuerübersicht","Wichtige Hinweise","Ihre Kontodaten IBAN BIC"})


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


class ComdirectFinanzreportPlugin(ComdirectPlugin):
 metadata=next(x for x in APPROVED_PLUGINS if x.plugin_id=="comdirect.finanzreport")
 def detect(self,doc): return (Detection(self.metadata.plugin_id,self.metadata.version,"finanzreport","comdirect Finanzreport",Decimal("0.99"),"Finanzreport header recognized"),) if re.search("comdirect",doc.text,re.I) and re.search(r"Finanzreport\s+Nr",doc.text,re.I) else ()
 def parse(self,doc,d):
  text=doc.text; ev,fv,evidence=evidence_recorder(doc,self.metadata.plugin_id,d.handler_id,self.metadata.version)
  header=re.search(r"Finanzreport\s+Nr\.?\s*(\S*)",text,re.I); header_ev=ev("document_type",header)
  period=re.search(r"(?:Berichtszeitraum|Zeitraum)\s*:?[ \t]*("+D+r")\s*(?:bis|-)\s*("+D+r")",text,re.I)
  report_dates={hit.group(1) for hit in FR_REPORT_DATE.finditer(text)}
  report_date=report_dates.pop() if len(report_dates)==1 else None
  lines=_finanzreport_lines(doc)
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
    issues.append(Issue(stable_id("issue",doc.document_id,"incomplete",block["offset"]),"INCOMPLETE_BOOKING",IssueSeverity.WARNING,"Buchungsblock ohne Betrag; Buchung wurde nicht übernommen.",nature=IssueNature.MISSING_INFORMATION)); return
   purpose=" ".join(block["body"]); key=(current,block["booked"],block["valuta"] or "",purpose,block["amount"])
   event_id=stable_id("event",*key)
   if key in seen:
    issues.append(Issue(stable_id("issue",event_id,"duplicate"),"DUPLICATE_BOOKING",IssueSeverity.WARNING,"Duplicate booking in Finanzreport.",event_id=event_id,nature=IssueNature.CONFIRMED_DEVIATION)); return
   seen.add(key)
   be=ev("booking","\n".join(block["raw"]),offset=block["offset"])
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
   # Verwahrentgelt (z. B. Xetra Gold): effektiv gebuchte Gebühr, mit der Kontobuchung verknüpft (kein zweiter Abzug).
   fees=(FeeEvent(stable_id("fee",event_id),"custody","verwahrentgelt",abs(block["amount"]),"EUR",date(block["booked"]),FeeEffect.ACTUAL_BOOKED,doc.document_id,"comdirect",account_id=current,transaction_id=event_id,cash_movement_id=movement.movement_id,evidence_ids=(be,)),) if custody else ()
   events.append(FinancialEvent(event_id,doc.document_id,"CASH_BOOKING",date(block["booked"]),(movement,),tax_events=taxes,fee_events=fees,evidence_ids=(be,)))

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
    flush_booking(); current=aid; depot_mode=False
    if account.group(3): overview[iban]=dec(account.group(3))
    elif index<len(lines) and FR_AMOUNT.fullmatch(lines[index][2]) and not FR_SALDO.match(lines[index][2]):
     overview[iban]=dec(lines[index][2]); index+=1
    continue
   heading=FR_HEADING.match(line)
   if heading:
    if heading.group(1)=="Tagesgeld" and index<len(lines) and lines[index][2].startswith("PLUS-Konto"):
     line="Tagesgeld "+lines[index][2]; index+=1; heading=FR_HEADING.match(line)
    lookahead=" | ".join(entry[2] for entry in lines[index:index+4])
    if "Buchungstag" in lookahead or "Alter Saldo" in lookahead:
     name=heading.group(1)
     iban=names.get(name.lower())
     if iban is None and name.lower().startswith("tagesgeld"): iban=names.get("tagesgeld plus-konto")
     if iban is None:
      raise ValueError("Finanzreport: Kontobereich ohne Kontoübersicht (IBAN fehlt) für "+heading.group(1)+".")
     flush_booking(); flush_position(); current=by_iban[iban]; section_accounts.add(current); depot_mode=False; depot_done=False
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
     flush_position(); pos={"wkn":head.group(1),"page":page,"offset":offset,"raw":[line],"name":"","quantity":None,"price":None,"price_currency":None,"value":None,"cost":None,"profit":None,"rest":[],"require_name":True}; continue
    if pos is not None:
     values=FR_POSITION_VALUES.match(line)
     if values and pos["value"] is None:
      pos.update(quantity=dec(values.group(1)),price=dec(values.group(2)),price_currency=values.group(3),value=dec(values.group(4))); pos["raw"].append(line); continue
     rest=FR_POSITION_REST.match(line)
     if rest and pos["value"] is not None:
      pos["rest"].extend(value for value in rest.groups() if value); pos["raw"].append(line); continue
     if pos["value"] is None:
      if re.match(r"^[A-Z0-9]{6}(?: /| \d[\d.]*,)",line):
       raise ValueError("Finanzreport: nicht unterstützte Depotposition: "+line)
      pos["name"]=(pos["name"]+" "+line).strip(); pos["raw"].append(line); continue
     continue
    row=FR_POSITION_ROW.match(line)
    if row:
     flush_position()
     pos={"wkn":row.group(1),"page":page,"offset":offset,"raw":[line],"name":None,"quantity":dec(row.group(2)),"price":dec(row.group(3)),"price_currency":"EUR","value":dec(row.group(4)),"cost":None,"profit":None,"rest":[],"require_name":False,"price_date":row.group(5)}
     flush_position(); continue
    continue
   row=FR_POSITION_ROW.match(line)
   if row and not depot_mode and current is None:
    flush_booking(); flush_position()
    pos={"wkn":row.group(1),"page":page,"offset":offset,"raw":[line],"name":None,"quantity":dec(row.group(2)),"price":dec(row.group(3)),"price_currency":"EUR","value":dec(row.group(4)),"cost":None,"profit":None,"rest":[],"require_name":False,"price_date":row.group(5)}
    flush_position(); continue
   if current is None: continue
   saldo=FR_SALDO.match(line)
   if saldo:
    flush_booking()
    amount=saldo.group(3); excerpt=line
    if amount is None and index<len(lines) and FR_AMOUNT.fullmatch(lines[index][2]):
     amount=lines[index][2]; excerpt=line+" "+amount; index+=1
    if amount is None:
     issues.append(Issue(stable_id("issue",current,"saldo",saldo.group(2)),"SALDO_AMOUNT_MISSING",IssueSeverity.WARNING,"Saldo ohne Betrag; Saldenprüfung entfällt.",nature=IssueNature.MISSING_INFORMATION)); continue
    se=ev(("opening_balance" if saldo.group(1)=="Alter" else "closing_balance"),excerpt,offset=offset)
    balances.append(AccountBalance(stable_id("balance",current,saldo.group(1).lower(),saldo.group(2)),current,fv(date(saldo.group(2)),se),fv(dec(amount),se),fv("EUR",se),FieldValue.manual("opening" if saldo.group(1)=="Alter" else "closing")))
    (opened if saldo.group(1)=="Alter" else closed)[current]=dec(amount)
    if saldo.group(1)=="Neuer": current=None
    continue
   row=FR_ROW.match(line)
   if row and not FR_DATE_LINE.fullmatch(line):
    flush_booking()
    pending={"booked":row.group(1),"valuta":row.group(2),"body":[row.group(3)],"raw":[line],"amount":dec(row.group(4)),"offset":offset,"page":page}
    flush_booking(); continue
   if FR_DATE_LINE.fullmatch(line):
    if pending is None or pending["amount"] is not None:
     flush_booking(); pending={"booked":line,"valuta":None,"body":[],"raw":[line],"amount":None,"offset":offset,"page":page}
    elif pending["valuta"] is None and not pending["body"]:
     pending["valuta"]=line; pending["raw"].append(line)
    else:
     pending["body"].append(line); pending["raw"].append(line)
    continue
   if FR_BOOKING_AMOUNT.fullmatch(line) and pending is not None and pending["amount"] is None:
    pending["amount"]=dec(line); pending["raw"].append(line); flush_booking(); continue
   if pending is not None:
    pending["body"].append(line); pending["raw"].append(line)
  flush_booking(); flush_position()

  for aid in section_accounts|{event.cash_movements[0].account_id for event in events if event.cash_movements and event.cash_movements[0].account_id}:
   total=sum((event.cash_movements[0].amount for event in events if event.cash_movements and event.cash_movements[0].account_id==aid),Decimal())
   if aid not in opened or aid not in closed:
    issues.append(Issue(stable_id("issue",aid,"saldo-missing"),"SALDO_MISSING",IssueSeverity.WARNING,"Anfangs- oder Endsaldo fehlt; Saldenprüfung entfällt.",nature=IssueNature.MISSING_INFORMATION)); continue
   if opened[aid]+total!=closed[aid]:
    issues.append(Issue(stable_id("issue",aid,"balance"),"BALANCE_MISMATCH",IssueSeverity.ERROR,"Finanzreport balance is inconsistent.",nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
   iban=next((key for key,value in by_iban.items() if value==aid),None)
   if iban is not None and iban in overview and overview[iban]!=closed[aid]:
    issues.append(Issue(stable_id("issue",aid,"overview"),"OVERVIEW_BALANCE_MISMATCH",IssueSeverity.ERROR,"Kontoübersicht und Endsaldo widersprechen sich.",nature=IssueNature.MATHEMATICAL_INCONSISTENCY))

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
    te=None; total_value=FieldValue.unknown()
    if depot_values:
     te=ev("depot_total","\n".join(depot_total_excerpt or ["Gesamtkurswert"]),offset=depot_total_offset)
     total_value=fv(depot_values[0],te)
    elif (total:=re.search(r"Depotgesamtwert\s+("+A+r")\s+EUR",text,re.I)):
     te=ev("depot_total",total); total_value=fv(dec(total.group(1)),te)
    dto_positions=[]
    for block in positions:
     pe=ev("depot_position","\n".join(block["raw"]),offset=block["offset"])
     price_date=date(block.get("price_date") or (report_date if report_date is not None else max(position_dates)))
     dto_positions.append(DepotPosition(stable_id("position",did,block["wkn"]),fv(block["wkn"],pe),fv(block["quantity"],pe),security_name=fv(block["name"],pe) if block["name"] else FieldValue.unknown(),market_value=fv(block["value"],pe),currency=fv("EUR",pe),price=fv(block["price"],pe) if block["price_currency"]=="EUR" else FieldValue.unknown(),price_date=fv(price_date,pe)))
    snapshots.append(DepotSnapshot(stable_id("snapshot",did,asof,doc.document_id),did,fv(asof,report_ev) if report_ev else fv(asof,dto_positions[0].price_date.evidence_ids[0]),tuple(dto_positions),total_value,fv("EUR",te) if te else FieldValue.unknown()))
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
  return ParsedDocument(stable_id("result",doc.document_id,self.metadata.version),doc.document_id,self.metadata.plugin_id,self.metadata.version,"finanzreport",events=tuple(events),evidence=tuple(evidence),issues=tuple(issues),attributes=attrs,accounts=tuple(accounts),account_balances=tuple(balances),depots=tuple(depots),depot_snapshots=tuple(snapshots),depot_account_links=tuple(links))
