from dataclasses import replace
from decimal import Decimal

import pytest

from portman_parsers.api import Detection, PdfDocument, PdfPage
from portman_parsers.registry import (
    APPROVED_PLUGINS,
    BLOCKED_MODULES,
    AmbiguousDetectionError,
    HandlerNotImplementedError,
    PluginRegistry,
    UnknownPluginError,
    metadata_registry,
)


class FakePlugin:
    def __init__(self, metadata, detections=()):
        self.metadata = metadata
        self._detections = detections

    def detect(self, document):
        return self._detections

    def parse(self, document, detection):
        raise AssertionError("not called")


def document():
    return PdfDocument("doc", "hash", (PdfPage(1, "synthetic"),))


def test_allowlist_has_eight_groups_ten_entry_points_and_42_handlers():
    assert len({item.group for item in APPROVED_PLUGINS}) == 8
    assert len(APPROVED_PLUGINS) == 10
    assert sum(len(item.handlers) for item in APPROVED_PLUGINS) == 42


def test_comdirect_has_three_entry_points():
    assert {item.plugin_id for item in APPROVED_PLUGINS if item.group == "comdirect"} == {
        "user.comdirect-ertraege", "comdirect.finanzreport", "portfolio-performance.comdirect"}


def test_excluded_plugins_are_blocked_and_absent():
    assert BLOCKED_MODULES == {"pbb_direkt", "baader_krypto"}
    assert all("pbb" not in item.plugin_id and "krypto" not in item.plugin_id
               for item in APPROVED_PLUGINS)


def test_metadata_placeholders_report_not_implemented():
    registry = metadata_registry()
    metadata = APPROVED_PLUGINS[0]
    handler = metadata.handlers[0]
    detection = Detection(metadata.plugin_id, metadata.version, handler.handler_id,
                          handler.document_type, Decimal("1"))
    with pytest.raises(HandlerNotImplementedError, match="NOT_IMPLEMENTED"):
        registry.parse(document(), detection)


def test_registry_rejects_unknown_or_modified_metadata():
    registry = PluginRegistry()
    with pytest.raises(UnknownPluginError):
        registry.register(FakePlugin(replace(APPROVED_PLUGINS[0], plugin_id="pbb.direkt")))
    with pytest.raises(ValueError, match="differs"):
        registry.register(FakePlugin(replace(APPROVED_PLUGINS[0], version="999")))


def test_selection_is_deterministic():
    metadata = APPROVED_PLUGINS[0]
    low = Detection(metadata.plugin_id, metadata.version, metadata.handlers[0].handler_id,
                    "low", Decimal("0.80"))
    high = Detection(metadata.plugin_id, metadata.version, metadata.handlers[0].handler_id,
                     "high", Decimal("0.95"))
    registry = PluginRegistry()
    registry.register(FakePlugin(metadata, (low, high)))
    assert registry.select(document()) == high


def test_ambiguous_top_confidence_is_reported():
    first, second = APPROVED_PLUGINS[:2]
    detections = (
        Detection(first.plugin_id, first.version, first.handlers[0].handler_id, "A", Decimal("0.9")),
        Detection(second.plugin_id, second.version, second.handlers[0].handler_id, "B", Decimal("0.9")),
    )
    registry = PluginRegistry()
    registry.register(FakePlugin(first, detections[:1]))
    registry.register(FakePlugin(second, detections[1:]))
    with pytest.raises(AmbiguousDetectionError, match="ambiguous"):
        registry.select(document())

