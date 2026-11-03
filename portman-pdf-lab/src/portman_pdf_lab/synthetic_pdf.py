"""Public, non-personal synthetic PDF used for demos and isolation checks."""

from pathlib import Path


BANK_OF_SCOTLAND_DEMO_TEXT = """Bank of Scotland
Lloyds Bank GmbH
Tagesgeld
Kontoinhaber: Erika Mustermann
Auszugsnummer: DEMO/2026
Datum: 31.12.2026
Kontonummer: 1234567890
IBAN: DE00 0000 0000 0000 0000 01
BIC: BOFSDEB1XXX
Buchungstag Wertstellung Beschreibung Soll Haben
01.12.2026 01.12.2026 Überweisung 100,00
31.12.2026 31.12.2026 Zinsen vor Steuern 10,00
31.12.2026 31.12.2026 Abgeltungssteuer 2,50
31.12.2026 31.12.2026 Solidaritätszuschlag 0,14
Gesamtsummen in Euro: 102,64 10,00
Alter Saldo: 1.000,00
Neuer Saldo: 907,36
RECHNUNGSABSCHLUSS"""


def create_demo_pdf(path: str | Path, text: str = BANK_OF_SCOTLAND_DEMO_TEXT) -> Path:
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
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data); data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets: data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    destination = Path(path); destination.write_bytes(data); return destination

