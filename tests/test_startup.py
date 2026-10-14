from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import importlib.util
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
from portman import startup


def test_editor_with_global_python_uses_project_environment(tmp_path, monkeypatch):
    entry = tmp_path / 'src' / 'Gui' / 'PortMan_V09.py'
    monkeypatch.setattr(startup.sys, 'executable', str(tmp_path / 'global-python.exe'))
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(startup.subprocess, 'run', run)
    with pytest.raises(SystemExit) as stopped:
        startup.use_project_python(entry, ['--example'])
    assert stopped.value.code == 0
    prepare_call, launch_call = run.call_args_list
    assert prepare_call.args[0][1] == str(tmp_path / 'tools' / 'prepare_environment.py')
    assert launch_call.args[0] == [str(tmp_path / '.venv' / 'Scripts' / 'python.exe'), str(entry), '--example']
    assert launch_call.kwargs['cwd'] == entry.parent


def test_preparation_failure_does_not_launch_app(tmp_path, monkeypatch):
    monkeypatch.setattr(startup.sys, 'executable', str(tmp_path / 'global-python.exe'))
    run = Mock(side_effect=subprocess.CalledProcessError(1, ['prepare']))
    monkeypatch.setattr(startup.subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        startup.use_project_python(tmp_path / 'src' / 'Gui' / 'PortMan_V09.py', [])
    assert run.call_count == 1


def test_project_python_keeps_debugger_and_sets_working_directory(tmp_path, monkeypatch):
    entry = tmp_path / 'src' / 'Gui' / 'PortMan_V09.py'
    entry.parent.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(startup.sys, 'executable', str(tmp_path / '.venv' / 'Scripts' / 'python.exe'))
    run = Mock()
    monkeypatch.setattr(startup.subprocess, 'run', run)
    startup.use_project_python(entry, [])
    run.assert_not_called()
    assert Path.cwd() == entry.parent


def test_missing_dependency_installs_only_into_project(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('portman_prepare', ROOT / 'tools' / 'prepare_environment.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    python = tmp_path / '.venv' / 'Scripts' / 'python.exe'
    python.parent.mkdir(parents=True)
    python.touch()
    run = Mock(side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0), SimpleNamespace(returncode=0)])
    monkeypatch.setattr(module.subprocess, 'run', run)
    module.prepare(tmp_path)
    install = run.call_args_list[1].args[0]
    assert install == [str(python), '-m', 'pip', 'install', '-r', str(tmp_path / 'requirements.txt')]
