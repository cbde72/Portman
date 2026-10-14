from pdf_plugins._statement_classification import classify_document, normalized_document_tags


def test_custom_document_tags_are_used_and_defaults_remain_for_missing_types():
    tags = {'Kontoauszug': ['Umsatzübersicht'], 'Steuerbescheinigung': ['Tax certificate']}
    assert classify_document(['Umsatzübersicht Oktober'], tags) == 'Kontoauszug'
    assert classify_document(['Tax certificate 2026'], tags) == 'Steuerbescheinigung'
    assert classify_document(['Eine Zinsmitteilung'], tags) == 'Zinsmitteilung'


def test_empty_or_duplicate_custom_tags_are_safely_normalized():
    tags = normalized_document_tags({'Depotauszug': [' Depotreport ', '', 'Depotreport']})
    assert tags['Depotauszug'] == ['Depotreport']
    assert tags['Kontoauszug']
