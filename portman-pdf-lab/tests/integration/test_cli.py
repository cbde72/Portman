import json
import subprocess
import sys


def test_cli_demo_emits_deterministic_shape():
    completed = subprocess.run([sys.executable, "-m", "portman_pdf_lab", "demo"],
                               check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    data = json.loads(completed.stdout)
    assert data["quality"]["events"] == 1
    assert data["quality"]["issues"] == {}

