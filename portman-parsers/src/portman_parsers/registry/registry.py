"""Deterministic registry without filesystem discovery."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from portman_parsers.api import Detection, ParsedDocument, PdfDocument

from .allowlist import APPROVED_PLUGINS, PluginMetadata


class UnknownPluginError(LookupError):
    pass


class AmbiguousDetectionError(RuntimeError):
    pass


class HandlerNotImplementedError(NotImplementedError):
    pass


@runtime_checkable
class ParserPlugin(Protocol):
    metadata: PluginMetadata

    def detect(self, document: PdfDocument) -> tuple[Detection, ...]: ...

    def parse(self, document: PdfDocument, detection: Detection) -> ParsedDocument: ...


@dataclass(frozen=True, slots=True)
class MetadataOnlyPlugin:
    metadata: PluginMetadata

    def detect(self, document: PdfDocument) -> tuple[Detection, ...]:
        return ()

    def parse(self, document: PdfDocument, detection: Detection) -> ParsedDocument:
        raise HandlerNotImplementedError(
            f"NOT_IMPLEMENTED: {self.metadata.plugin_id}/{detection.handler_id}")


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ParserPlugin] = {}

    def register(self, plugin: ParserPlugin) -> None:
        plugin_id = plugin.metadata.plugin_id
        if plugin_id not in {item.plugin_id for item in APPROVED_PLUGINS}:
            raise UnknownPluginError(f"plugin is not approved: {plugin_id}")
        if plugin_id in self._plugins:
            raise ValueError(f"plugin already registered: {plugin_id}")
        expected = next(item for item in APPROVED_PLUGINS if item.plugin_id == plugin_id)
        if plugin.metadata != expected:
            raise ValueError(f"plugin metadata differs from the approved contract: {plugin_id}")
        self._plugins[plugin_id] = plugin

    def plugin(self, plugin_id: str) -> ParserPlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise UnknownPluginError(plugin_id) from exc

    def metadata(self) -> tuple[PluginMetadata, ...]:
        return tuple(self._plugins[key].metadata for key in sorted(self._plugins))

    def detect(self, document: PdfDocument) -> tuple[Detection, ...]:
        found = [detection for key in sorted(self._plugins)
                 for detection in self._plugins[key].detect(document)]
        return tuple(sorted(found, key=lambda item: (
            -item.confidence, item.plugin_id, item.handler_id)))

    def select(self, document: PdfDocument, minimum: Decimal = Decimal("0.70")) -> Detection | None:
        candidates = [item for item in self.detect(document) if item.confidence >= minimum]
        if not candidates:
            return None
        best = candidates[0]
        tied = [item for item in candidates if item.confidence == best.confidence]
        unique = {(item.plugin_id, item.handler_id) for item in tied}
        if len(unique) > 1:
            choices = ", ".join(f"{plugin}/{handler}" for plugin, handler in sorted(unique))
            raise AmbiguousDetectionError(f"ambiguous detection at {best.confidence}: {choices}")
        return best

    def parse(self, document: PdfDocument, detection: Detection) -> ParsedDocument:
        plugin = self.plugin(detection.plugin_id)
        handler = next((item for item in plugin.metadata.handlers
                        if item.handler_id == detection.handler_id), None)
        if handler is None:
            raise UnknownPluginError(
                f"unknown handler: {detection.plugin_id}/{detection.handler_id}")
        if not handler.implemented:
            raise HandlerNotImplementedError(
                f"NOT_IMPLEMENTED: {detection.plugin_id}/{detection.handler_id}")
        return plugin.parse(document, detection)


def metadata_registry() -> PluginRegistry:
    registry = PluginRegistry()
    for metadata in APPROVED_PLUGINS:
        registry.register(MetadataOnlyPlugin(metadata))
    return registry


def default_registry() -> PluginRegistry:
    from portman_parsers.plugins import BankOfScotlandPlugin, ComdirectPlugin, ComdirectFinanzreportPlugin, ComdirectPPPlugin, FnzFinvestoPlugin
    registry = PluginRegistry()
    for metadata in APPROVED_PLUGINS:
        if metadata.plugin_id == "user.bank-of-scotland-kontoauszug":
            plugin = BankOfScotlandPlugin()
        elif metadata.plugin_id == "fnz.finvesto":
            plugin = FnzFinvestoPlugin()
        elif metadata.plugin_id == "user.comdirect-ertraege":
            plugin = ComdirectPlugin()
        elif metadata.plugin_id == "comdirect.finanzreport":
            plugin = ComdirectFinanzreportPlugin()
        elif metadata.plugin_id == "portfolio-performance.comdirect":
            plugin = ComdirectPPPlugin()
        else:
            plugin = MetadataOnlyPlugin(metadata)
        registry.register(plugin)
    return registry

