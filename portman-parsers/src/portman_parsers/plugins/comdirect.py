"""Independent comdirect handlers; no V09 compatibility layer."""
from datetime import datetime
from decimal import Decimal
import re
from portman_parsers.api import *
from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.utilities import stable_id

A=r"\d[\d.]*,\d+"; D=r"\d{2}\.\d{2}\.\d{4}"
TITLES=(("kosteninformation_mifid_ii",r"Kosteninformation\s+zum\s+Wertpapiergesch"),("vorabpauschale",r"Steuerliche\s+Behandlung:\s*Vorabpauschale"),("investment_ausschuettung",r"Steuerliche\s*Behandlung:.*Investment-Aussch"),("dividende_steuer_inland",r"Steuerliche\s*Behandlung:.*Dividende"),("dividendengutschrift",r"Abrechnung\s*Dividendengutschrift"),("ertragsgutschrift",r"Abrechnung\s*Ertragsgutschrift"),("einloesung",r"Abrechnung\s*Einl[öo]sung"),("wertpapierkauf",r"Wertpapierkauf"),("wertpapierverkauf",r"Wertpapierverkauf"))
ISIN=re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b"); IBAN=re.compile(r"DE(?:\s*\d){20}"); DEPOT=re.compile(r"Depot(?:nummer|nr\.)\s*:?\s*(\d+(?:\s+\d+)?)",re.I)
QTY=re.compile(r"(?:Stk\.?|STK)\s*("+A+r")",re.I); VALUTA=re.compile(r"(?:Valuta|zahlbar\s+ab)\s*("+D+r")",re.I)
WKN=re.compile(r"\bWKN\s*:?[ \t]*([A-Z0-9]{6})\b",re.I)
TRADE_DATE=re.compile(r"(?:Geschäftstag|Schlusstag)\s*:?[ \t]*("+D+r")",re.I)
EXECUTION_DATE=re.compile(r"(?:Ausführungstag|Ausführung)\s*:?[ \t]*("+D+r")",re.I)
PRICE=re.compile(r"(?:Ausführungskurs|Kurs)\s*:?[ \t]*(?:(?P<cur1>[A-Z]{3})\s*)?(?P<a>"+A+r")(?:\s*(?P<cur2>[A-Z]{3}))?",re.I)
MARKET_VALUE=re.compile(r"(?:Kurswert|Gegenwert)\s*:?[ \t]*(?P<cur>[A-Z]{3})\s*(?P<a>"+A+r")",re.I)
GROSS=re.compile(r"(?:Bruttobetrag|Bruttoertrag|Bruttodividende)\s*:?[ \t]*(?P<cur>[A-Z]{3})\s*(?P<a>"+A+r")",re.I)
FX=re.compile(r"(?:Devisenkurs|Umrechnungskurs)\s*:?[ \t]*("+A+r")",re.I)
NAME=re.compile(r"(?:Wertpapierbezeichnung|Bezeichnung)\s*:?[ \t]*(.+)",re.I)
SETTLE=re.compile(r"(?:Zu\s*Ihren\s*(?P<dir>Lasten|Gunsten)|(?:^|\n)Gutschrift|(?:^|\n)Zahlungsbetrag).{0,80}?(?P<cur>[A-Z]{3})\s*-?\s*(?P<a>"+A+r")",re.I|re.S)
TAX=(("CAPITAL_GAINS_TAX",r"Kapitalertragsteuer\s*(?:EUR)?\s*-?("+A+r")"),("SOLIDARITY_SURCHARGE",r"Solidarit.tszuschlag\s*(?:EUR)?\s*-?("+A+r")"),("CHURCH_TAX",r"Kirchensteuer\s*(?:EUR)?\s*-?("+A+r")"),("WITHHOLDING_TAX",r"Quellensteuer\s*(?:[A-Z]{3})?\s*-?("+A+r")"))
FEE=(("provision",r"Provision\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("foreign_expenses",r"(?:Fremdspesen|fremde\s+Spesen)\s*:?\s*(?:EUR)?\s*-?("+A+r")"),("exchange_fee",r"(?:B.rsenplatz.*Entgelt|B.rsengeb.hr)\s*:?\s*(?:EUR)?\s*-?("+A+r")"))
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
  text=doc.text; evidence=[]
  def ev(field,excerpt):
   page=next((p.number for p in doc.pages if excerpt in p.text),1); eid=stable_id("evidence",doc.document_id,page,field,excerpt,len(evidence))
   evidence.append(Evidence(eid,doc.document_id,page,field,excerpt,f"page:{page}",doc.source_hash,self.metadata.plugin_id,d.handler_id,self.metadata.version)); return eid
  title=re.search(next(p for h,p in TITLES if h==d.handler_id),text,re.I|re.S).group(0); eid=ev("document_type",title)
  isin=ISIN.search(text).group(0) if ISIN.search(text) else None; depot_m=DEPOT.search(text); depot_id=None; depots=()
  if depot_m:
   number=re.sub(r"\s", "",depot_m.group(1)); de=ev("depot_number",depot_m.group(0)); depot_id=stable_id("depot","comdirect",number)
   depots=(Depot(depot_id,bank_name=FieldValue.from_pdf("comdirect",1,de),depot_number=FieldValue.from_pdf(number,1,de),base_currency=FieldValue.from_pdf("EUR",1,de),depot_type=FieldValue.manual(DepotType.WERTPAPIER)),)
  if d.handler_id=="kosteninformation_mifid_ii":
   cost_patterns=(("PRODUCT_COST",r"Produktkosten[^\n]*?("+A+r")\s*EUR"),("SERVICE_COST",r"Dienstleistungskosten[^\n]*?("+A+r")\s*EUR"),("ONE_OFF_COST",r"Einmalige Kosten[^\n]*?("+A+r")\s*EUR"),("ONGOING_COST",r"Laufende Kosten[^\n]*?("+A+r")\s*EUR"),("TRANSACTION_COST",r"Transaktionskosten[^\n]*?("+A+r")\s*EUR"),("INDUCEMENT",r"Zuwendungen[^\n]*?("+A+r")\s*EUR"))
   event_id=stable_id("event",doc.document_id,d.handler_id); info_type=CostInformationType.MIFID_EX_POST if re.search(r"ex[ -]?post",text,re.I) else CostInformationType.MIFID_EX_ANTE
   costs=[]
   for kind,pattern in cost_patterns:
    m=re.search(pattern,text,re.I)
    if m:
     ce=ev(kind.lower(),m.group(0)); costs.append(CostEvent(stable_id("cost",event_id,kind),event_id,kind,dec(m.group(1)),"EUR",informational=True,evidence_ids=(ce,),information_type=info_type,document_id=doc.document_id,bank_id="comdirect",depot_id=depot_id,security_id=isin))
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
  return self.transaction(doc,d,evidence,ev,depots,depot_id,isin,eid)
 def transaction(self,doc,d,evidence,ev,depots,depot_id,isin,eid):
  text=doc.text; h=d.handler_id; kind="BUY" if h=="wertpapierkauf" else "SELL" if h=="wertpapierverkauf" else "REDEMPTION" if h=="einloesung" else "DIVIDEND"
  q=QTY.search(text); qty=dec(q.group(1)) if q else None; settlement=SETTLE.search(text); valuta=VALUTA.search(text); event_id=stable_id("event",doc.document_id,h,isin,settlement.group("a") if settlement else "")
  issues=[]
  for code,missing,message in (("COMDIRECT_SECURITY_MISSING",not isin,"Wertpapieridentität fehlt."),("COMDIRECT_QUANTITY_MISSING",qty is None,"Stückzahl fehlt."),("COMDIRECT_SETTLEMENT_MISSING",settlement is None,"Settlementbetrag fehlt.")):
   if missing: issues.append(Issue(stable_id("issue",event_id,code),code,IssueSeverity.WARNING,message,event_id=event_id,nature=IssueNature.MISSING_INFORMATION))
  event_ev=ev("economic_event",settlement.group(0) if settlement else next(p for x,p in TITLES if x==h)); iban=IBAN.search(text); account_id=None; accounts=()
  if iban:
   identity=re.sub(r"\s","",iban.group(0)); ie=ev("iban",iban.group(0)); account_id=stable_id("account","comdirect",identity); accounts=(Account(account_id,bank_name=FieldValue.from_pdf("comdirect",1,ie),iban=FieldValue.from_pdf(identity,1,ie),currency=FieldValue.from_pdf("EUR",1,ie)),)
  links=()
  if depot_id and account_id:
   links=(DepotAccountLink(stable_id("depot-account",depot_id,account_id,doc.document_id),depot_id,account_id,FieldValue.from_pdf("SETTLEMENT",1,ie),valid_from=FieldValue.from_pdf(date(valuta.group(1)),1,event_ev) if valuta else FieldValue.unknown(),is_default=FieldValue.manual(False)),)
  cash=()
  if settlement:
   sign=-1 if kind=="BUY" or (settlement.group("dir") or "").lower()=="lasten" else 1; cash=(CashMovement(stable_id("cash",event_id),event_id,dec(settlement.group("a"))*sign,settlement.group("cur"),CashStatus.ACTUAL if account_id else CashStatus.EXPECTED,account_id=account_id,evidence_ids=(event_ev,),movement_type=CashMovementType.SECURITY_BUY if kind=="BUY" else CashMovementType.SECURITY_SELL if kind in {"SELL","REDEMPTION"} else CashMovementType.DIVIDEND_CREDIT),)
  security=() if not(qty and isin) else (SecurityMovement(stable_id("security",event_id),event_id,isin,qty if kind=="BUY" else -qty,(event_ev,),depot_id),)
  fees=tuple(FeeEvent(stable_id("fee",event_id,k),"trading",k,dec(m.group(1)),"EUR",date(valuta.group(1)) if valuta else date("01.01.1970"),FeeEffect.INCLUDED_IN_SETTLEMENT,doc.document_id,"comdirect",depot_id=depot_id,account_id=account_id,security_id=isin,transaction_id=event_id,evidence_ids=(event_ev,)) for k,p in FEE for m in [re.search(p,text,re.I)] if m)
  comps=tuple(TaxComponent(k,dec(m.group(1)),"EUR") for k,p in TAX for m in [re.search(p,text,re.I)] if m); taxes=(TaxEvent(stable_id("tax",event_id),event_id,"WITHHOLDING",comps,evidence_ids=(event_ev,),depot_id=depot_id,isin=isin,bank_id="comdirect",account_id=account_id),) if comps else ()
  trades=()
  if kind in {"BUY","SELL","REDEMPTION"}:
   pm=PRICE.search(text); mm=MARKET_VALUE.search(text); gm=GROSS.search(text); fx=FX.search(text); wm=WKN.search(text); nm=NAME.search(text); tm=TRADE_DATE.search(text); xm=EXECUTION_DATE.search(text)
   trades=(SecurityTrade(stable_id("trade",event_id),event_id,kind,nm.group(1).strip() if nm else MissingValue.NOT_FOUND,isin or MissingValue.NOT_FOUND,wm.group(1).upper() if wm else MissingValue.NOT_FOUND,qty if qty is not None else MissingValue.NOT_FOUND,date(tm.group(1)) if tm else MissingValue.NOT_FOUND,date(xm.group(1)) if xm else MissingValue.NOT_FOUND,date(valuta.group(1)) if valuta else MissingValue.NOT_FOUND,dec(pm.group("a")) if pm else MissingValue.NOT_FOUND,(pm.group("cur1") or pm.group("cur2")) if pm and (pm.group("cur1") or pm.group("cur2")) else MissingValue.NOT_FOUND,dec(mm.group("a")) if mm else MissingValue.NOT_FOUND,dec(gm.group("a")) if gm else MissingValue.NOT_FOUND,dec(fx.group(1)) if fx else MissingValue.NOT_FOUND,dec(settlement.group("a")) if settlement else MissingValue.NOT_FOUND,settlement.group("cur") if settlement else MissingValue.NOT_FOUND,depot_id,account_id,(event_ev,)),)
  event=FinancialEvent(event_id,doc.document_id,kind,date(valuta.group(1)) if valuta else None,cash,security,tax_events=taxes,fee_events=fees,evidence_ids=(event_ev,),trades=trades); return self.result(doc,d,evidence,(event,),depots,accounts,tuple(issues),links)
 def result(self,doc,d,evidence,events,depots=(),accounts=(),issues=(),links=(),tax_calculations=(),tax_carryforwards=()): return ParsedDocument(stable_id("result",doc.document_id,self.metadata.version),doc.document_id,self.metadata.plugin_id,self.metadata.version,d.handler_id,events=events,evidence=tuple(evidence),issues=issues,depots=depots,accounts=accounts,depot_account_links=links,tax_calculations=tax_calculations,tax_carryforwards=tax_carryforwards)

class ComdirectFinanzreportPlugin(ComdirectPlugin):
 metadata=next(x for x in APPROVED_PLUGINS if x.plugin_id=="comdirect.finanzreport")
 def detect(self,doc): return (Detection(self.metadata.plugin_id,self.metadata.version,"finanzreport","comdirect Finanzreport",Decimal("0.99"),"Finanzreport header recognized"),) if re.search("comdirect",doc.text,re.I) and re.search(r"Finanzreport\s+Nr",doc.text,re.I) else ()
 def parse(self,doc,d):
  text=doc.text; evidence=[]
  def ev(field,excerpt):
   page=next((p.number for p in doc.pages if excerpt in p.text),1); eid=stable_id("evidence",doc.document_id,page,field,excerpt,len(evidence)); evidence.append(Evidence(eid,doc.document_id,page,field,excerpt,f"page:{page}",doc.source_hash,self.metadata.plugin_id,"finanzreport",self.metadata.version)); return eid
  header=re.search(r"Finanzreport\s+Nr\.?\s*(\S*)",text,re.I); ev("document_type",header.group(0))
  period=re.search(r"(?:Berichtszeitraum|Zeitraum)\s*:?[ \t]*("+D+r")\s*(?:bis|-)\s*("+D+r")",text,re.I)
  account_matches=list(re.finditer(r"(?m)^(Girokonto|Verrechnungskonto|Tagesgeld(?: PLUS)?(?:-Konto)?)\s+(DE(?:\s*\d){20})\s*$",text,re.I))
  accounts=[]; events=[]; balances=[]; issues=[]; seen_bookings=set()
  for index,match in enumerate(account_matches):
   section=text[match.end():account_matches[index+1].start() if index+1<len(account_matches) else len(text)]; iban=re.sub(r"\s","",match.group(2)); aid=stable_id("account","comdirect",iban); ie=ev("account",match.group(0)); at=AccountType.GIRO if "giro" in match.group(1).lower() else AccountType.OTHER
   accounts.append(Account(aid,bank_name=FieldValue.from_pdf("comdirect",1,ie),account_type=FieldValue.from_pdf(at,1,ie),iban=FieldValue.from_pdf(iban,1,ie),currency=FieldValue.from_pdf("EUR",1,ie),functions=(FieldValue.manual(AccountFunction.PAYMENT if at==AccountType.GIRO else AccountFunction.SETTLEMENT),)))
   opening=re.search(r"Alter\s+Saldo\s+("+D+r")\s+([+-]?"+A+r")",section,re.I); closing=re.search(r"Neuer\s+Saldo\s+("+D+r")\s+([+-]?"+A+r")",section,re.I)
   for row in re.finditer(r"(?m)^("+D+r")\s+("+D+r")\s+(.+?)\s+([+-]"+A+r")\s*$",section):
    revid=ev("booking",row.group(0)); amount=dec(row.group(4)); key=(aid,row.group(1),row.group(2),row.group(3).strip(),amount); event_id=stable_id("event",*key)
    if key in seen_bookings:
     issues.append(Issue(stable_id("issue",event_id,"duplicate"),"DUPLICATE_BOOKING",IssueSeverity.WARNING,"Duplicate booking in Finanzreport.",revid,event_id,IssueNature.CONFIRMED_DEVIATION)); continue
    seen_bookings.add(key); movement=CashMovement(stable_id("cash",event_id),event_id,amount,"EUR",CashStatus.ACTUAL,account_id=aid,evidence_ids=(revid,),movement_type=CashMovementType.OTHER); events.append(FinancialEvent(event_id,doc.document_id,"CASH_BOOKING",date(row.group(1)),(movement,),evidence_ids=(revid,)))
   if opening and closing:
    oe=ev("opening_balance",opening.group(0)); ce=ev("closing_balance",closing.group(0)); balances.extend((AccountBalance(stable_id("balance",aid,"open",opening.group(1)),aid,FieldValue.from_pdf(date(opening.group(1)),1,oe),FieldValue.from_pdf(dec(opening.group(2)),1,oe),FieldValue.from_pdf("EUR",1,oe),FieldValue.manual("opening")),AccountBalance(stable_id("balance",aid,"close",closing.group(1)),aid,FieldValue.from_pdf(date(closing.group(1)),1,ce),FieldValue.from_pdf(dec(closing.group(2)),1,ce),FieldValue.from_pdf("EUR",1,ce),FieldValue.manual("closing"))))
    total=sum((e.cash_movements[0].amount for e in events if e.cash_movements[0].account_id==aid),Decimal())
    if dec(opening.group(2))+total!=dec(closing.group(2)): issues.append(Issue(stable_id("issue",aid,"balance"),"BALANCE_MISMATCH",IssueSeverity.ERROR,"Finanzreport balance is inconsistent.",ce,nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
  depots=[]; snapshots=[]; depot_m=DEPOT.search(text)
  if depot_m:
   number=re.sub(r"\s","",depot_m.group(1)); de=ev("depot_number",depot_m.group(0)); did=stable_id("depot","comdirect",number); depots.append(Depot(did,bank_name=FieldValue.from_pdf("comdirect",1,de),depot_number=FieldValue.from_pdf(number,1,de),base_currency=FieldValue.from_pdf("EUR",1,de),depot_type=FieldValue.manual(DepotType.WERTPAPIER)))
   positions=[]
   for row in re.finditer(r"(?m)^([A-Z]{2}[A-Z0-9]{9}\d)\s+("+A+r")\s+("+A+r")\s+EUR\s+("+A+r")\s+EUR\s+("+D+r")\s*$",text):
    pe=ev("depot_position",row.group(0)); positions.append(DepotPosition(stable_id("position",did,row.group(1)),FieldValue.from_pdf(row.group(1),1,pe),FieldValue.from_pdf(dec(row.group(2)),1,pe),market_value=FieldValue.from_pdf(dec(row.group(4)),1,pe),currency=FieldValue.from_pdf("EUR",1,pe),price=FieldValue.from_pdf(dec(row.group(3)),1,pe),price_date=FieldValue.from_pdf(date(row.group(5)),1,pe)))
   total=re.search(r"Depotgesamtwert\s+("+A+r")\s+EUR",text,re.I)
   if positions:
    te=ev("depot_total",total.group(0)) if total else positions[0].market_value.evidence_ids[0]; asof=max(p.price_date.value for p in positions); reported=FieldValue.from_pdf(dec(total.group(1)),1,te) if total else FieldValue.unknown(); snapshots.append(DepotSnapshot(stable_id("snapshot",did,asof,doc.document_id),did,FieldValue.from_pdf(asof,1,positions[0].price_date.evidence_ids[0]),tuple(positions),reported,FieldValue.from_pdf("EUR",1,te)))
    if total and sum((p.market_value.value for p in positions),Decimal())!=dec(total.group(1)): issues.append(Issue(stable_id("issue",did,"total"),"DEPOT_TOTAL_MISMATCH",IssueSeverity.ERROR,"Depot position sum differs from total.",te,nature=IssueNature.MATHEMATICAL_INCONSISTENCY))
  links=[]
  if depots and accounts:
   for match in re.finditer(r"(?:Abrechnungs|Verrechnungs|Settlement)konto\s*:?[ \t]*(DE(?:\s*\d){20})",text,re.I):
    iban=re.sub(r"\s","",match.group(1)); account=next((x for x in accounts if x.iban.value==iban),None)
    if account:
     le=ev("depot_account_link",match.group(0)); links.append(DepotAccountLink(stable_id("depot-account",depots[0].depot_id,account.account_id,doc.document_id),depots[0].depot_id,account.account_id,FieldValue.from_pdf("SETTLEMENT",1,le),valid_from=FieldValue.from_pdf(date(period.group(1)),1,le) if period else FieldValue.unknown(),is_default=FieldValue.manual(False)))
  attrs={"document_number":header.group(1) or MissingValue.NOT_FOUND,"period_start":period.group(1) if period else MissingValue.NOT_FOUND,"period_end":period.group(2) if period else MissingValue.NOT_FOUND,"layout_path":"core" if re.search(r"IBAN|Depotgesamtwert",text,re.I) else "legacy"}
  return ParsedDocument(stable_id("result",doc.document_id,self.metadata.version),doc.document_id,self.metadata.plugin_id,self.metadata.version,"finanzreport",events=tuple(events),evidence=tuple(evidence),issues=tuple(issues),attributes=attrs,accounts=tuple(accounts),account_balances=tuple(balances),depots=tuple(depots),depot_snapshots=tuple(snapshots),depot_account_links=tuple(links))
