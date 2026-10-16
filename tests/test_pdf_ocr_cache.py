from pathlib import Path


def test_seed_model_cache_copies_models_once_and_keeps_them(tmp_path):
    from portfolio_v5.pdf_ocr import seed_model_cache
    source = tmp_path / 'package-models'
    target = tmp_path / 'persistent-models'
    source.mkdir()
    (source / 'det.onnx').write_bytes(b'model-data')
    (source / '.gitkeep').write_bytes(b'')

    assert seed_model_cache(source, target) == target
    assert (target / 'det.onnx').read_bytes() == b'model-data'
    assert not (target / '.gitkeep').exists()
    first_mtime = (target / 'det.onnx').stat().st_mtime_ns
    seed_model_cache(source, target)
    assert (target / 'det.onnx').stat().st_mtime_ns == first_mtime

    # A package update can replace a model without changing its byte length.
    (source / 'det.onnx').write_bytes(b'new-model!')
    assert len(b'new-model!') == len(b'model-data')
    seed_model_cache(source, target)
    assert (target / 'det.onnx').read_bytes() == b'new-model!'


def test_persistent_model_dir_uses_local_app_data(monkeypatch, tmp_path):
    from portfolio_v5.pdf_ocr import persistent_model_dir
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert persistent_model_dir() == Path(tmp_path) / 'PortMan' / 'rapidocr-models'
