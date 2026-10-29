import unittest
from pdf_parser_audit_v2 import enrich, full_delta

class TestAuditV2(unittest.TestCase):
    def row(self, name='x.pdf', warnings=None, errors=None):
        return {'path':name,'plugin':'baader.pdf','handler':'trade','sha256':'abcdef', 'warnings':warnings or [],'errors':errors or []}

    def test_plugin_notice_is_info(self):
        self.assertEqual(enrich(self.row(warnings=['PDF-Plugin: Baader · trade · Erkennung 100%']))['severity'],'INFO')

    def test_buy_positive_is_warning(self):
        x=enrich(self.row(warnings=['Buchung: Kauf mit positivem Betrag (Abfluss muss negativ sein)']))
        self.assertEqual(x['severity'],'WARNING')
        self.assertIn('BUY_POSITIVE',x['issue_codes'])

    def test_hard_error(self):
        self.assertEqual(enrich(self.row(errors=['PDF konnte nicht gelesen werden: crash']))['severity'],'ERROR')

    def test_v1_comparison(self):
        prior={'files':[self.row(warnings=['Kauf mit positivem Betrag'])]}
        now=[enrich(self.row(warnings=['PDF-Plugin: erkannt']))]
        d=full_delta(now,prior,True)
        self.assertEqual(len(d['resolved']),1)
        self.assertFalse(d['regressions'])

    def test_targeted_not_removed(self):
        prior={'files':[self.row('a.pdf'),self.row('b.pdf')]}
        d=full_delta([enrich(self.row('a.pdf'))],prior,False)
        self.assertEqual(d['removed'],[])

    def test_same_status_new_warning_regression(self):
        prior={'files':[self.row(warnings=['Kauf mit positivem Betrag'])]}
        now=[enrich(self.row(warnings=['Kauf mit positivem Betrag','Brutto/Netto passt nicht']))]
        self.assertEqual(len(full_delta(now,prior,True)['regressions']),1)

if __name__=='__main__':unittest.main()
