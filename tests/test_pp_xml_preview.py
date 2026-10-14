"""Portfolio-Performance-XML-Vorschauimport: Kontenzuordnung und Dublettenprüfung."""
import pytest

from portfolio_v5.models import ImportBatch, Snapshot, Position
from portman.pp_xml_preview import parse_pp_xml, preview_pp_xml, preview_pp_file, save_pp_preview
from portman.repository_v09 import RepositoryV09


PAYLOAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<portfolio version="70">
  <securities>
    <security>
      <uuid>SEC-1</uuid>
      <name>Vanguard FTSE All-World</name>
      <isin>IE00B3RBWM25</isin>
      <ticker>VGWL</ticker>
      <currency>EUR</currency>
    </security>
  </securities>
  <accounts>
    <account>
      <uuid>ACC-1</uuid>
      <name>Depot ING</name>
      <currency>EUR</currency>
    </account>
    <account>
      <uuid>ACC-2</uuid>
      <name>Depot Unbekannt</name>
      <currency>EUR</currency>
    </account>
  </accounts>
  <portfolio-transactions>
    <portfolio-transaction>
      <uuid>TX-1</uuid>
      <date>2026-01-05T00:00:00</date>
      <account reference="ACC-1"/>
      <security reference="SEC-1"/>
      <type>Buy</type>
      <amount>5000</amount>
      <shares>10</shares>
      <fees>5</fees>
    </portfolio-transaction>
    <portfolio-transaction>
      <uuid>TX-2</uuid>
      <date>2026-02-01T00:00:00</date>
      <account reference="ACC-1"/>
      <security reference="SEC-1"/>
      <type>Sell</type>
      <amount>2000</amount>
      <shares>4</shares>
    </portfolio-transaction>
    <portfolio-transaction>
      <uuid>TX-3</uuid>
      <date>2026-02-10T00:00:00</date>
      <account reference="ACC-1"/>
      <security reference="SEC-9"/>
      <type>Dividend</type>
      <amount>50</amount>
    </portfolio-transaction>
    <portfolio-transaction>
      <uuid>TX-4</uuid>
      <date>2026-02-12T00:00:00</date>
      <account reference="ACC-8"/>
      <security reference="SEC-1"/>
      <type>Buy</type>
      <amount>100</amount>
    </portfolio-transaction>
    <portfolio-transaction>
      <uuid>TX-5</uuid>
      <date>2026-02-15T00:00:00</date>
      <account reference="ACC-1"/>
      <security reference="SEC-1"/>
      <type>Unbekannt</type>
      <amount>0</amount>
    </portfolio-transaction>
  </portfolio-transactions>
</portfolio>
"""


@pytest.fixture
def repo(tmp_path):
    repository = RepositoryV09(tmp_path / 'pp.sqlite', backups=False)
    repository.commit_batches([ImportBatch('seed', 'seed', snapshots=[Snapshot(
        'Depot ING', '2026-01', '2026-01-05', 'test',
        [Position('X1', 'Vanguard FTSE All-World', isin='IE00B3RBWM25',
                  value='1000', currency='EUR')])])])
    yield repository
    repository.close()


def test_parse_reads_containers_and_resolves_references():
    parsed = parse_pp_xml(PAYLOAD)
    assert parsed['version'] == 70
    assert [s['uuid'] for s in parsed['securities']] == ['SEC-1']
    assert parsed['securities'][0]['isin'] == 'IE00B3RBWM25'
    assert {a['uuid'] for a in parsed['accounts']} == {'ACC-1', 'ACC-2'}
    first = parsed['transactions'][0]
    assert first['uuid'] == 'TX-1'
    assert first['account_uuid'] == 'ACC-1'
    assert first['security_uuid'] == 'SEC-1'
    assert first['date'] == '2026-01-05'
    assert first['type'] == 'Buy'


def test_preview_matches_security_by_isin_and_account_by_name(repo):
    preview = preview_pp_xml(repo, PAYLOAD)
    summary = preview['summary']
    assert summary['securities'] == 1 and summary['securities_matched'] == 1
    assert summary['accounts'] == 2 and summary['accounts_matched'] == 1
    by_uuid = {account['uuid']: account['assignment'] for account in preview['accounts']}
    assert by_uuid['ACC-1'] == 'Depot ING'
    assert by_uuid['ACC-2'] is None
    rows = {row['uuid']: row for row in preview['transactions']}
    assert rows['TX-1']['status'] == 'ok'
    assert rows['TX-1']['signed_amount'] == '-5000'
    assert rows['TX-1']['account'] == 'Depot ING'
    assert rows['TX-1']['security_key'] == 'X1'
    assert rows['TX-2']['status'] == 'ok' and rows['TX-2']['signed_amount'] == '2000'
    assert rows['TX-3']['status'] == 'unknown_security'
    assert rows['TX-4']['status'] == 'unknown_account'
    assert rows['TX-5']['status'] == 'invalid'
    assert summary['importable'] == 2


def test_file_duplicates_are_flagged(repo):
    extra = PAYLOAD.replace(
        b'<uuid>TX-2</uuid>',
        b'<uuid>TX-6</uuid>').replace(
        b'<type>Sell</type>',
        b'<type>Sell</type>', 1)
    # Append a transaction that repeats TX-1's business fingerprint.
    duplicate = b'''<portfolio-transaction>
      <uuid>TX-6</uuid>
      <date>2026-01-05T00:00:00</date>
      <account reference="ACC-1"/>
      <security reference="SEC-1"/>
      <type>Buy</type>
      <amount>5000</amount>
      <shares>10</shares>
    </portfolio-transaction>'''
    payload = extra.replace(b'</portfolio-transactions>', duplicate + b'</portfolio-transactions>')
    preview = preview_pp_xml(repo, payload)
    rows = {row['uuid']: row for row in preview['transactions']}
    assert rows['TX-1']['status'] == 'ok'
    assert rows['TX-6']['status'] == 'duplicate'
    assert rows['TX-6']['duplicate_of'] == 'Dateidublette'
    assert preview['summary']['duplicates'] == 1


def test_save_imports_only_matched_rows_and_marks_them_duplicate(repo):
    preview = preview_pp_xml(repo, PAYLOAD)
    result = save_pp_preview(repo, preview)
    assert result['imported'] == 2
    ids = {transaction['external_id'] for transaction in repo.transactions()}
    assert {'pp:TX-1', 'pp:TX-2'} <= ids
    assert 'pp:TX-3' not in ids and 'pp:TX-4' not in ids

    second = preview_pp_xml(repo, PAYLOAD)
    statuses = {row['uuid']: row['status'] for row in second['transactions']}
    assert statuses['TX-1'] == 'duplicate' and statuses['TX-2'] == 'duplicate'
    assert second['summary']['importable'] == 0


def test_preview_file_reads_container_from_disk(repo, tmp_path):
    path = tmp_path / 'export.xml'
    path.write_bytes(PAYLOAD)
    preview = preview_pp_file(repo, path)
    assert preview['source'] == str(path)
    assert preview['summary']['importable'] == 2
