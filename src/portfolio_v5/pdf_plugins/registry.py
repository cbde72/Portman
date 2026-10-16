import os
import importlib.util
from importlib.metadata import entry_points
from pathlib import Path

from .config import ConfigPdfPlugin


def _is_plugin(plugin):
    return (plugin is not None and all(hasattr(plugin, name) for name in ('plugin_id', 'bank_name', 'version'))
            and callable(getattr(plugin, 'detect', None)) and callable(getattr(plugin, 'parse', None)))


def profile_directories(extra=()):
    configured = [Path(item) for item in os.environ.get('PORTMAN_PDF_PLUGIN_PATH', '').split(os.pathsep) if item]
    project_plugins = Path(__file__).resolve().parents[3] / 'pdf_plugins'
    return [project_plugins, Path.cwd() / 'pdf_plugins', Path.home() / '.portman' / 'pdf_plugins',
            *configured, *map(Path, extra)]


def discover_plugins(profile_dirs=()):
    plugins, errors = [], []
    for group in ('portman.pdf_importers', 'portman.pdf_importer'):
        for entry in entry_points().select(group=group):
            try:
                candidate = entry.load()
                plugin = candidate() if isinstance(candidate, type) else candidate
                if not _is_plugin(plugin): raise TypeError('Plugin erfüllt PdfImporterPlugin nicht.')
                plugins.append(plugin)
            except Exception as error: errors.append(f'{entry.name}: {error}')
    seen_files = set()
    for directory in profile_directories(profile_dirs):
        if not directory.is_dir(): continue
        for path in sorted(directory.glob('*.toml')):
            if path.resolve() in seen_files: continue
            seen_files.add(path.resolve())
            try: plugins.append(ConfigPdfPlugin(path))
            except Exception as error: errors.append(f'{path}: {error}')
        for path in sorted(directory.glob('*.py')):
            if path.name.startswith('_') or path.resolve() in seen_files: continue
            seen_files.add(path.resolve())
            try:
                name = '_portman_pdf_plugin_' + str(abs(hash(path.resolve())))
                spec = importlib.util.spec_from_file_location(name, path)
                if spec is None or spec.loader is None: raise ImportError('Python-Datei kann nicht geladen werden.')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                candidate = getattr(module, 'plugin', None) or getattr(module, 'Plugin', None)
                plugin = candidate() if isinstance(candidate, type) else candidate
                if not _is_plugin(plugin):
                    raise TypeError('Datei muss „plugin“ oder „Plugin“ mit PdfImporterPlugin bereitstellen.')
                plugin.source_path = path
                plugins.append(plugin)
            except Exception as error: errors.append(f'{path}: {error}')
    ids = set(); unique = []
    for plugin in plugins:
        if plugin.plugin_id in ids:
            errors.append(f'{plugin.plugin_id}: Plugin-ID mehrfach registriert.')
            continue
        ids.add(plugin.plugin_id); unique.append(plugin)
    return unique, errors


def select_plugin(document, plugins, minimum=.70, errors=None):
    candidates = []
    for plugin in plugins:
        try:
            detections = plugin.detect(document)
        except Exception as error:
            if errors is not None: errors.append(f'{plugin.plugin_id}: Erkennung fehlgeschlagen: {error}')
            continue
        for detection in detections:
            if not 0 <= detection.confidence <= 1: raise ValueError(f'{plugin.plugin_id}: ungültige Erkennungssicherheit.')
            candidates.append((detection.confidence, plugin.plugin_id, detection.handler_id, plugin, detection))
    # A plugin may emit the same handler more than once from overlapping
    # signatures. It is one candidate, not artificial evidence or ambiguity.
    unique = {}
    for candidate in candidates:
        key = candidate[1], candidate[2]
        if key not in unique or candidate[0] > unique[key][0]:
            unique[key] = candidate
    candidates = sorted(unique.values(), key=lambda item: item[:3], reverse=True)
    if not candidates or candidates[0][0] < minimum: return None
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .10:
        first, second = candidates[:2]
        raise ValueError(f'PDF passt mehrdeutig zu {first[1]}/{first[2]} und {second[1]}/{second[2]}. Erkennungsregeln der Plugins präzisieren.')
    return candidates[0][3], candidates[0][4]
