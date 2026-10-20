"""Preview (default) or explicitly apply conservative security-name repairs."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from portman.security_names import apply_repairs, repair_preview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="apply exactly the displayed name-only repairs")
    args = parser.parse_args()
    target = args.database.resolve()
    db = (sqlite3.connect(target) if args.apply else
          sqlite3.connect("file:" + target.as_posix() + "?mode=ro", uri=True))
    db.row_factory = sqlite3.Row
    try:
        preview = repair_preview(db)
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        if args.apply:
            print(f"{apply_repairs(db, preview)} Wertpapiername(n) repariert.")
        else:
            print(f"Vorschau: {len(preview)} mögliche Reparatur(en); keine Daten geändert.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
