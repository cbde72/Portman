"""Preserve rotated native text and report degraded table layout to the reviewer."""
import logging
import threading


def extract_page_text(page):
    thread_id = threading.get_ident()
    rotated = False

    class ExtractionWarning(logging.Filter):
        def filter(self, record):
            nonlocal rotated
            message = record.getMessage()
            if record.thread == thread_id and (message.startswith('Rotated text discovered.') or
                                                message.startswith('PDF contains an uninterpretable font.')):
                rotated = True
                return False  # Replaced by a page-specific warning in the import preview.
            return True

    logger = logging.getLogger('pypdf._text_extraction._layout_mode._fixed_width_page')
    notice = ExtractionWarning()
    logger.addFilter(notice)
    try:
        try:
            layout = page.extract_text(extraction_mode='layout') or ''
        except Exception:
            layout = ''
            rotated = True  # Failed layout also needs a reviewed plain-text fallback.
    finally:
        logger.removeFilter(notice)
    if rotated:
        try:
            return page.extract_text(extraction_mode='plain', orientations=(0, 90, 180, 270)) or layout, True
        except Exception:
            return layout, True
    return layout, False
