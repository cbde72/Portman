import logging
import unittest
from unittest.mock import Mock

from portfolio_v5.pdf_text import extract_page_text


class PdfTextTests(unittest.TestCase):
    def test_regular_tables_keep_layout_and_single_extraction(self):
        page = Mock()
        page.extract_text.return_value = 'Datum       Betrag\n01.01.2026  10,00'
        text, review = extract_page_text(page)
        self.assertIn('       ', text)
        self.assertFalse(review)
        page.extract_text.assert_called_once_with(extraction_mode='layout')

    def test_rotated_text_is_recovered_without_duplicate_text(self):
        logger = logging.getLogger('pypdf._text_extraction._layout_mode._fixed_width_page')
        original_filters = list(logger.filters)
        def extract(**options):
            if options['extraction_mode'] == 'layout':
                logger.warning('Rotated text discovered. Output will be incomplete.')
                return 'Heading'
            self.assertEqual(options['orientations'], (0, 90, 180, 270))
            return 'Heading\nRotated booking 100 EUR'
        text, review = extract_page_text(Mock(extract_text=extract))
        self.assertEqual(text, 'Heading\nRotated booking 100 EUR')
        self.assertTrue(review)
        self.assertEqual(logger.filters, original_filters)

    def test_failed_layout_uses_plain_text(self):
        page = Mock()
        page.extract_text.side_effect = [ValueError('layout failed'), 'Plain booking']
        self.assertEqual(extract_page_text(page), ('Plain booking', True))

    def test_uninterpretable_font_warning_is_suppressed_and_requires_review(self):
        logger = logging.getLogger('pypdf._text_extraction._layout_mode._fixed_width_page')
        original_filters = list(logger.filters)
        def extract(**options):
            if options['extraction_mode'] == 'layout':
                logger.warning('PDF contains an uninterpretable font. Output will be incomplete.')
                return 'Unvollständiger Text'
            return 'Text aus alternativer Extraktion'
        text, review = extract_page_text(Mock(extract_text=extract))
        self.assertEqual(text, 'Text aus alternativer Extraktion')
        self.assertTrue(review)
        self.assertEqual(logger.filters, original_filters)

    def test_failed_fallback_retains_available_text_and_requires_review(self):
        logger = logging.getLogger('pypdf._text_extraction._layout_mode._fixed_width_page')
        def extract(**options):
            if options['extraction_mode'] == 'layout':
                logger.warning('Rotated text discovered. Output will be incomplete.')
                return 'Available heading'
            raise ValueError('plain failed')
        self.assertEqual(extract_page_text(Mock(extract_text=extract)), ('Available heading', True))
