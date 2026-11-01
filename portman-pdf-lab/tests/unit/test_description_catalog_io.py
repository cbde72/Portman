"""Robustness tests for the persistent description catalog."""

import json
import warnings

from portman_pdf_lab.field_descriptions import DescriptionCatalog


def test_empty_description_store_rebuilds(tmp_path):
    path = tmp_path / "field-descriptions.v1.json"
    path.write_text("", encoding="utf-8")
    store = DescriptionCatalog.load(path)
    store.resolve("accounts[0].bank_name.value")
    store.save()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["entries"][0]["description"] == "Name der kontoführenden Bank"


def test_corrupt_nonempty_store_is_preserved(tmp_path):
    path = tmp_path / "field-descriptions.v1.json"
    path.write_text("{corrupted", encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        store = DescriptionCatalog.load(path)
    assert caught
    assert store.path is None
    assert store.resolve("accounts[0].bank_name.value").description
    assert path.read_text(encoding="utf-8") == "{corrupted"


def test_atomic_save_produces_valid_json_and_no_temp_files(tmp_path):
    path = tmp_path / "field-descriptions.v1.json"
    store = DescriptionCatalog.load(path)
    store.resolve("accounts[0].bank_name.value")
    store.save()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert not list(tmp_path.glob(".field-descriptions-*.tmp"))
