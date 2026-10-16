import os
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from portfolio_v5.models import BankTransaction, ImportBatch, digest
from portfolio_v5.accounts import account_key
from portman.repository_v09 import RepositoryV09, reference


@pytest.fixture
def repo(tmp_path):
    repo = RepositoryV09(tmp_path/'portfolio.sqlite', backups=False)
    repo.create_accounts(['Konto A', 'Konto B'])
    yield repo
    repo.close()


def batch(kind, label, *, target='Konto A', count=1, reference='ABC1234567890XYZ/987', purpose='Monatsmiete Wohnung Hauptstrasse', amount='-100', valuta='2026-10-01'):
    source = 'PDF Konto' if kind == 'pdf' else 'Online Konto'
    txs = [BankTransaction(source,f'{kind}-booking-{label}-{n}','2026-10-01','BANK_BOOKING',amount,'EUR',
                          value_date=valuta,purpose=purpose,bank_reference=reference) for n in range(count)]
    return ImportBatch(f'{label}.{ "pdf" if kind=="pdf" else "bank"}',digest(label),transactions=txs,
                       account_assignments={account_key(source):account_key(target)})


@pytest.mark.parametrize('order',[('online','pdf'),('pdf','online')])
def test_import_order_repeats_and_undo_keep_one_payment(repo,order):
    first, second = (batch(kind, f'file-{i}') for i,kind in enumerate(order))
    a=repo.store.import_batch(first);b=repo.store.import_batch(second)
    txs=repo.transactions()
    assert len(txs)==1 and len(txs[0]['booking_sources'])==2
    assert repo.store.db.execute('SELECT count(*) FROM transactions').fetchone()[0]==2
    assert repo.store.import_batch(second)['status']=='duplicate'
    assert len(repo.transactions())==1
    repo.store.undo_import(a['id'])
    assert len(repo.transactions())==1 and repo.transactions()[0]['import_id']==b['id']
    repo.store.undo_import(b['id'])
    assert repo.transactions()==[]


def test_comdirect_split_reference_matches_but_prefix_alone_does_not(repo):
    online=batch('online','sync')
    pdf=batch('pdf','statement',reference='ABC1234567890',purpose='Andere Spaltenfolge')
    pdf.transactions[0].raw_text='ABC1234567890\nGegenpartei\nXYZ/987\nText'
    repo.store.import_batch(online);repo.store.import_batch(pdf)
    assert len(repo.transactions())==1
    other=batch('pdf','wrong',reference='ABC1234567890',purpose='Unabhängige Zahlung')
    other.transactions[0].raw_text='ABC1234567890\nANDERE/123'
    repo.store.import_batch(other)
    assert len(repo.transactions())==2


@pytest.mark.parametrize('first_count,second_count',[(2,2),(1,2),(2,1)])
def test_genuine_repeated_payments_preserve_occurrences(repo,first_count,second_count):
    repo.store.import_batch(batch('online','sync',count=first_count))
    repo.store.import_batch(batch('pdf','statement',count=second_count))
    assert len(repo.transactions())==max(first_count,second_count)


def test_different_accounts_amounts_dates_or_references_stay_separate(repo):
    repo.store.import_batch(batch('online','sync'))
    for label,change in [('otheraccount',{'target':'Konto B'}),('otherref',{'reference':'DIFFERENT1234'}),
                         ('amount',{'amount':'-200'}),('valuta',{'valuta':'2026-10-02'})]:
        repo.store.import_batch(batch('pdf',label,**change))
    assert len(repo.transactions())==5


def test_no_amount_only_or_generic_text_matching(repo):
    repo.store.import_batch(batch('online','sync',reference='',purpose='Überweisung'))
    repo.store.import_batch(batch('pdf','statement',reference='',purpose='Überweisung'))
    assert len(repo.transactions())==2


def test_full_text_without_reference_and_pdf_repeats(repo):
    repo.store.import_batch(batch('online','sync',reference='NONREF'))
    repo.store.import_batch(batch('pdf','statement',reference=''))
    repo.store.import_batch(batch('pdf','statement-again',reference=''))
    assert len(repo.transactions())==1


def test_repeated_online_references_with_different_ids(repo):
    repo.store.import_batch(batch('online','sync1'))
    repo.store.import_batch(batch('online','sync2'))
    assert len(repo.transactions())==1


def test_classification_survives_a_second_source(repo):
    repo.store.import_batch(batch('online','sync'))
    tx=repo.transactions()[0];ref=reference(tx)
    repo.classify(ref,'FEE','','','Geprüft')
    repo.store.import_batch(batch('pdf','statement'))
    txs=repo.transactions()
    assert len(txs)==1 and txs[0]['kind']=='FEE' and reference(txs[0])==ref


def test_complementary_details_retained(repo):
    online=batch('online','sync');online.transactions[0].counterparty_iban='DE89370400440532013000'
    pdf=batch('pdf','statement');pdf.transactions[0].raw_text='Vollständiger Originaltext\nZweite Zeile'
    repo.store.import_batch(online);repo.store.import_batch(pdf)
    tx=repo.transactions()[0]
    assert tx['counterparty_iban']=='DE89370400440532013000'
    assert 'Zweite Zeile' in tx['raw_text']
    from portfolio_v5.booking_details import full_booking_text
    assert 'sync.bank' in full_booking_text(tx) and 'statement.pdf' in full_booking_text(tx)


def test_trade_confirmation_adds_provision_to_matching_statement_booking(repo):
    statement = batch('pdf', 'finanzreport', reference='REPORT-REF', amount='-41.95',
                      valuta='2026-07-27', purpose='ISH.S.EUROP.MID 200 U.ETF WPKNR: 593399 ISIN: DE0005933998')
    statement.transactions[0].date = '2026-07-23'
    statement.transactions[0].booking_text = 'ISH.S.EUROP.MID 200 U.ETF\nWPKNR: 593399 ISIN: DE0005933998'
    confirmation = batch('pdf', 'abrechnung', reference='', amount='-41.95',
                         valuta='2026-07-27', purpose='Wertpapierabrechnung')
    trade = confirmation.transactions[0]
    # The settlement match is driven by valuta, not by an identical booking day.
    trade.date = '2026-07-22'
    trade.booking_text = 'ISH.S.EUROP.MID200U.ETF\nWPKNR: 593399 ISIN: DE0005933998'
    trade.security = 'DE0005933998'
    trade.quantity = '0.620'
    trade.fees = '0.62'
    trade.gross_amount = '41.33'
    trade.fee_items = [{'kind': 'provision', 'amount': '0.62'}]
    trade.field_sources = {'fees': 'comdirect Wertpapierabrechnung · Provision'}

    repo.store.import_batch(statement)
    repo.store.import_batch(confirmation)
    transactions = repo.transactions()
    assert len(transactions) == 1
    assert (transactions[0]['security'], transactions[0]['quantity'], transactions[0]['fees']) == (
        'DE0005933998', '0.620', '0.62')
    assert transactions[0]['gross_amount'] == '41.33'
    assert len(transactions[0]['booking_sources']) == 2


def test_distinct_security_orders_with_same_day_and_amount_are_not_merged(repo):
    first = batch('pdf', 'order-one', reference='', amount='-100',
                  purpose='Kauf ISIN: DE0005933998', valuta='2026-07-27')
    second = batch('online', 'order-two', reference='', amount='-100',
                   purpose='Kauf ISIN: DE0005933998', valuta='2026-07-27')
    first.transactions[0].security = second.transactions[0].security = 'DE0005933998'
    first.transactions[0].order_id = 'ORDER-ONE'
    second.transactions[0].order_id = 'ORDER-TWO'
    repo.store.import_batch(first)
    repo.store.import_batch(second)
    assert len(repo.transactions()) == 2


def test_reassignment_rechecks_account_boundary(repo):
    repo.store.import_batch(batch('online','sync'))
    imported=repo.store.import_batch(batch('pdf','statement'))
    assert len(repo.transactions())==1
    change=dict(import_id=imported['id'],source_key=account_key('PDF Konto'),target_key=account_key('Konto B'))
    repo.reassign_imports([change])
    assert len(repo.transactions('Konto A'))==len(repo.transactions('Konto B'))==1
    change['target_key']=account_key('Konto A');repo.reassign_imports([change])
    assert len(repo.transactions())==1


def test_missing_valuta_and_different_decimal_format_can_match(repo):
    repo.store.import_batch(batch('online','sync',amount='-100.0',valuta=''))
    repo.store.import_batch(batch('pdf','statement',amount='-100.00'))
    assert len(repo.transactions())==1


def test_conflicting_counterparty_ibans_never_match(repo):
    online=batch('online','sync');online.transactions[0].counterparty_iban='DE89370400440532013000'
    pdf=batch('pdf','statement');pdf.transactions[0].counterparty_iban='DE12500105170648489890'
    repo.store.import_batch(online);repo.store.import_batch(pdf)
    assert len(repo.transactions())==2


def test_superseded_record_cannot_hide_the_active_replacement(repo):
    first=repo.store.import_batch(batch('online','sync'))
    second=repo.store.import_batch(batch('pdf','statement'))
    with repo.db:
        repo.db.execute('INSERT INTO transaction_supersessions(old_import,old_account,old_id,new_import,new_account,new_id,reason) VALUES(?,?,?,?,?,?,?)',
                        (first['id'],'Online Konto','online-booking-sync-0',second['id'],'PDF Konto','pdf-booking-statement-0','Korrektur'))
    txs=repo.transactions()
    assert len(txs)==1 and txs[0]['import_id']==second['id']


def test_same_transaction_affects_balance_once(repo):
    repo.add_balance('Konto A','1000','2026-09-30')
    repo.store.import_batch(batch('online','sync'))
    repo.store.import_batch(batch('pdf','statement'))
    rows={r['name']:r for r in repo.account_overview('2026-10-01')}
    assert rows['Konto A']['balance']==900


def test_repository_classification_cache_is_separate_from_store(repo):
    repo.store.import_batch(batch('online','sync'))
    raw=repo.store.transactions()[0]
    with repo.db:
        repo.db.execute('INSERT INTO transaction_classifications(ref,kind,security,quantity,reason) VALUES(?,?,?,?,?)',
                        (reference(raw),'FEE','',None,'Geprüft'))
    assert repo.store.transactions()[0]['kind']=='BANK_BOOKING'
    assert repo.transactions()[0]['kind']=='FEE'
    assert repo._read_cache is not repo.store._read_cache
