"""Safe container inspection for Portfolio Performance files.

This module deliberately stops before mapping PP entities into Portman.  It is
the small, testable boundary that makes sure later import code only receives a
bounded, plain XML document.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


DEFAULT_MAX_XML_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 200


class PortfolioPerformanceFormat(StrEnum):
    XML = "xml"
    ZIP_XML = "zip-xml"
    PROTOBUF = "protobuf"
    ZIP_PROTOBUF = "zip-protobuf"
    ENCRYPTED = "encrypted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PortfolioPerformanceInspection:
    format: PortfolioPerformanceFormat
    version: int | None = None
    counts: dict[str, int] | None = None


def _xml_start(data: bytes) -> bool:
    return data.startswith(b"\xef\xbb\xbf") or data.lstrip().startswith(b"<")


def _safe_zip_member(archive: ZipFile, max_xml_bytes: int):
    files = [item for item in archive.infolist() if not item.is_dir()]
    if len(files) != 1:
        raise ValueError("Die Portfolio-Performance-ZIP-Datei muss genau eine Datendatei enthalten.")
    item = files[0]
    path = PurePosixPath(item.filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Die ZIP-Datei enthält einen unsicheren Dateipfad.")
    if item.file_size > max_xml_bytes:
        raise ValueError("Die entpackte Portfolio-Performance-Datei ist zu groß.")
    if item.compress_size == 0:
        ratio = item.file_size if item.file_size else 1
    else:
        ratio = item.file_size / item.compress_size
    if ratio > DEFAULT_MAX_COMPRESSION_RATIO:
        raise ValueError("Die ZIP-Datei weist ein unsicheres Kompressionsverhältnis auf.")
    return item


def detect_portfolio_performance_format(path, max_xml_bytes=DEFAULT_MAX_XML_BYTES):
    """Detect the PP container without deserializing its object graph."""
    source = Path(path)
    with source.open("rb") as handle:
        prefix = handle.read(64)
    if prefix.startswith(b"PORTFOLIO"):
        return PortfolioPerformanceFormat.ENCRYPTED
    if prefix.startswith(b"PK\x03\x04"):
        try:
            with ZipFile(source) as archive:
                item = _safe_zip_member(archive, max_xml_bytes)
                with archive.open(item) as stream:
                    inner_prefix = stream.read(64)
        except BadZipFile as exc:
            raise ValueError("Die Portfolio-Performance-ZIP-Datei ist beschädigt.") from exc
        if item.filename.lower().endswith(".portfolio") and not _xml_start(inner_prefix):
            return PortfolioPerformanceFormat.ZIP_PROTOBUF
        return PortfolioPerformanceFormat.ZIP_XML if _xml_start(inner_prefix) else PortfolioPerformanceFormat.ZIP_PROTOBUF
    if _xml_start(prefix):
        return PortfolioPerformanceFormat.XML
    if source.suffix.lower() == ".portfolio":
        return PortfolioPerformanceFormat.PROTOBUF
    return PortfolioPerformanceFormat.UNKNOWN


def read_portfolio_performance_xml(path, max_xml_bytes=DEFAULT_MAX_XML_BYTES):
    """Return bounded XML bytes; reject executable XML constructs and other PP formats."""
    source = Path(path)
    kind = detect_portfolio_performance_format(source, max_xml_bytes)
    if kind == PortfolioPerformanceFormat.XML:
        if source.stat().st_size > max_xml_bytes:
            raise ValueError("Die Portfolio-Performance-XML-Datei ist zu groß.")
        data = source.read_bytes()
    elif kind == PortfolioPerformanceFormat.ZIP_XML:
        with ZipFile(source) as archive:
            item = _safe_zip_member(archive, max_xml_bytes)
            data = archive.read(item)
    elif kind == PortfolioPerformanceFormat.ENCRYPTED:
        raise ValueError("Verschlüsselte Portfolio-Performance-Dateien werden noch nicht unterstützt. Bitte in Portfolio Performance als XML speichern.")
    elif kind in (PortfolioPerformanceFormat.PROTOBUF, PortfolioPerformanceFormat.ZIP_PROTOBUF):
        raise ValueError("Binäre Portfolio-Performance-Dateien werden noch nicht unterstützt. Bitte in Portfolio Performance als XML speichern.")
    else:
        raise ValueError("Das Dateiformat wurde nicht als Portfolio-Performance-XML erkannt.")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("XML-Dokumenttypen und externe Entitäten sind aus Sicherheitsgründen nicht erlaubt.")
    return data


def inspect_portfolio_performance_file(path, max_xml_bytes=DEFAULT_MAX_XML_BYTES):
    """Inspect type and basic XML contents without interpreting references."""
    kind = detect_portfolio_performance_format(path, max_xml_bytes)
    if kind not in (PortfolioPerformanceFormat.XML, PortfolioPerformanceFormat.ZIP_XML):
        return PortfolioPerformanceInspection(kind)
    try:
        root = ElementTree.fromstring(read_portfolio_performance_xml(path, max_xml_bytes))
    except ElementTree.ParseError as exc:
        raise ValueError("Die Portfolio-Performance-XML-Datei ist beschädigt.") from exc
    version_text = root.attrib.get("version")
    try:
        version = int(version_text) if version_text is not None else None
    except ValueError:
        version = None
    names = {"account", "portfolio", "security", "account-transaction", "portfolio-transaction", "price"}
    counts = {name: 0 for name in names}
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name in counts:
            counts[local_name] += 1
    return PortfolioPerformanceInspection(kind, version, counts)
