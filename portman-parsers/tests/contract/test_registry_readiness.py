from portman_parsers.registry.allowlist import APPROVED_PLUGINS
from portman_parsers.registry import default_registry


def test_allowlist_exposes_explicit_handler_readiness():
    handlers = [handler for plugin in APPROVED_PLUGINS for handler in plugin.handlers]
    assert len(handlers) == 42
    assert sum(handler.readiness == "IMPLEMENTED" for handler in handlers) == 29
    assert sum(handler.readiness == "METADATA_ONLY" for handler in handlers) == 13
    assert {handler.readiness for handler in handlers} <= {"IMPLEMENTED", "PARTIAL", "METADATA_ONLY", "DISABLED"}


def test_registry_reports_same_readiness_for_manual_lookup():
    registry = default_registry()
    assert registry.handler_status("user.comdirect-ertraege", "dividendengutschrift") == "IMPLEMENTED"
    assert registry.handler_status("baader.pdf", "dividende") == "METADATA_ONLY"
