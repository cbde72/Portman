from pathlib import Path

import pytest
import yaml

from portman_pdf_lab.field_catalog import CatalogStore
from portman_pdf_lab.field_catalog_adapter import import_factual_catalog
from portman_pdf_lab.field_descriptions import DescriptionCatalog, DescriptionEntry, resolve_description


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "data" / "Portman_PDF_Lab_Feldkatalog_v1.0.0.yaml"


def test_factual_catalog_import_maps_full_dto_paths_and_writes_audit(tmp_path):
    audit = import_factual_catalog(SOURCE, tmp_path / "field-descriptions.v1.json",
                                   tmp_path / "field-catalog.audit.json")
    assert audit["summary"]["total"] == 170
    assert audit["summary"]["mapped"] > 0
    assert audit["summary"]["unknown"] > 0
    assert audit["summary"]["deviating"] > 0
    assert any(item["dto_path"] == "events[].trades[].quantity" for item in audit["mapped"])
    assert any(item["catalog_path"] == "securities[].ticker" for item in audit["unknown_paths"])


def test_factual_descriptions_use_index_and_value_wrapper_without_overwriting_verified(tmp_path):
    path = tmp_path / "field-descriptions.v1.json"
    descriptions = DescriptionCatalog((DescriptionEntry("events[].trades[].quantity", "Bestätigte Definition", "test", status="VERIFIED"),), path)
    descriptions.save()
    import_factual_catalog(SOURCE, path, tmp_path / "audit.json")
    loaded = DescriptionCatalog.load(path)
    assert resolve_description("events[3].trades[0].quantity.value", description_catalog=loaded).description == "Bestätigte Definition"


def test_catalog_store_exposes_adapter_and_schema_version_is_checked(tmp_path):
    store = CatalogStore(tmp_path)
    audit = store.import_factual_catalog(SOURCE, tmp_path / "audit.json")
    assert audit["schema_version"] == "1.0"
    assert (tmp_path / "field-descriptions.v1.json").exists()


def test_incompatible_factual_catalog_version_is_rejected(tmp_path):
    payload = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    payload["schema_version"] = "9.9"
    source = tmp_path / "incompatible.yaml"
    source.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported factual field catalog schema"):
        import_factual_catalog(source, tmp_path / "descriptions.json")
