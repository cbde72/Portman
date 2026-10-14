from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from portman.portfolio_performance_import import (
    PortfolioPerformanceFormat,
    detect_portfolio_performance_format,
    inspect_portfolio_performance_file,
    read_portfolio_performance_xml,
)


XML = b'''<?xml version="1.0"?><client version="70"><securities><security/></securities><accounts><account/></accounts><account-transaction/><portfolio-transaction/><price/></client>'''


def test_plain_xml_is_detected_and_summarized(tmp_path):
    path = tmp_path / "sample.xml"
    path.write_bytes(XML)
    result = inspect_portfolio_performance_file(path)
    assert result.format == PortfolioPerformanceFormat.XML
    assert result.version == 70
    assert result.counts == {
        "account": 1,
        "portfolio": 0,
        "security": 1,
        "account-transaction": 1,
        "portfolio-transaction": 1,
        "price": 1,
    }


def test_zipped_xml_and_binary_containers_are_distinguished(tmp_path):
    xml_zip = tmp_path / "sample.zip"
    with ZipFile(xml_zip, "w", ZIP_DEFLATED) as archive:
        archive.writestr("client.xml", XML)
    assert detect_portfolio_performance_format(xml_zip) == PortfolioPerformanceFormat.ZIP_XML
    assert read_portfolio_performance_xml(xml_zip) == XML

    binary = tmp_path / "sample.portfolio"
    binary.write_bytes(b"\x08\x01\x12\x03abc")
    assert detect_portfolio_performance_format(binary) == PortfolioPerformanceFormat.PROTOBUF
    with pytest.raises(ValueError, match="Binäre"):
        read_portfolio_performance_xml(binary)


def test_encrypted_and_unsafe_xml_are_rejected(tmp_path):
    encrypted = tmp_path / "secret.portfolio"
    encrypted.write_bytes(b"PORTFOLIO" + b"\x00" * 30)
    assert detect_portfolio_performance_format(encrypted) == PortfolioPerformanceFormat.ENCRYPTED
    with pytest.raises(ValueError, match="Verschlüsselte"):
        read_portfolio_performance_xml(encrypted)

    entity = tmp_path / "entity.xml"
    entity.write_bytes(b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><client>&y;</client>')
    with pytest.raises(ValueError, match="Entitäten"):
        read_portfolio_performance_xml(entity)


def test_zip_with_multiple_files_or_traversal_is_rejected(tmp_path):
    multiple = tmp_path / "multiple.zip"
    with ZipFile(multiple, "w") as archive:
        archive.writestr("one.xml", XML)
        archive.writestr("two.xml", XML)
    with pytest.raises(ValueError, match="genau eine"):
        detect_portfolio_performance_format(multiple)

    traversal = tmp_path / "traversal.zip"
    with ZipFile(traversal, "w") as archive:
        archive.writestr("../client.xml", XML)
    with pytest.raises(ValueError, match="unsicheren Dateipfad"):
        detect_portfolio_performance_format(traversal)
