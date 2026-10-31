import json
from pathlib import Path
import subprocess
import sys

from portman_pdf_lab.application import analyse_directory, analyse_pdf


TEXT = (Path(__file__).parents[1] / "fixtures" / "bank_of_scotland_statement.txt").read_text(encoding="utf-8")


def pdf_bytes(text):
    commands = ["BT /F1 9 Tf 30 760 Td"]
    for index, line in enumerate(text.splitlines()):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj" if index == 0 else f"0 -12 Td ({escaped}) Tj")
    commands.append("ET"); stream = "\n".join(commands).encode("latin-1")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    data = bytearray(b"%PDF-1.4\n"); offsets = []
    for number, obj in enumerate(objects, 1): offsets.append(len(data)); data.extend(f"{number} 0 obj\n".encode()+obj+b"\nendobj\n")
    xref=len(data); data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets: data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()); return bytes(data)


def test_complete_pdf_analysis_and_stage_timings(tmp_path):
    path = tmp_path / "statement.pdf"; path.write_bytes(pdf_bytes(TEXT))
    report = analyse_pdf(path)
    assert report["detection"]["plugin_id"] == "user.bank-of-scotland-kontoauszug"
    assert report["result"]["accounts"][0]["account_type"]["value"] == "TAGESGELD"
    assert len(report["result"]["events"]) == 4
    assert set(report["timings"]) == {"extraction_ns", "detection_ns", "parsing_ns",
                                        "validation_ns", "reporting_ns", "total_ns"}


def test_cli_exports_json_report(tmp_path):
    path = tmp_path / "statement.pdf"; path.write_bytes(pdf_bytes(TEXT)); output = tmp_path / "report.json"
    completed = subprocess.run([sys.executable, "-m", "portman_pdf_lab", "analyze", str(path),
                                "--output", str(output)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["result"]["events"]


def test_batch_continues_after_unreadable_pdf(tmp_path):
    (tmp_path / "good.pdf").write_bytes(pdf_bytes(TEXT)); (tmp_path / "bad.pdf").write_bytes(b"broken")
    report = analyse_directory(tmp_path)
    assert report["count"] == 2
    assert {"result", "error"} <= {key for item in report["files"] for key in item}
