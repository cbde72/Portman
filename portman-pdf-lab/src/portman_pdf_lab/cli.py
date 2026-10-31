import argparse
import json
from pathlib import Path
from typing import Sequence

from .demo import run_demo
from .application.pdf_analysis import analyse_directory, analyse_pdf, export_batch_csv
from .synthetic_pdf import create_demo_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portman-pdf-lab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("demo", help="run a synthetic demonstration")
    create = subparsers.add_parser("create-demo-pdf", help="write a synthetic Bank of Scotland PDF")
    create.add_argument("path")
    analyse = subparsers.add_parser("analyze", help="analyze one local PDF")
    analyse.add_argument("path")
    analyse.add_argument("--output", "-o")
    batch = subparsers.add_parser("batch", help="analyze PDFs recursively and sequentially")
    batch.add_argument("path")
    batch.add_argument("--output", "-o")
    batch.add_argument("--csv")
    subparsers.add_parser("gui", help="start the independent desktop GUI")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        result = run_demo()
    elif args.command == "create-demo-pdf":
        result = {"created": str(create_demo_pdf(args.path))}
    elif args.command == "analyze":
        result = analyse_pdf(args.path)
    elif args.command == "batch":
        result = analyse_directory(args.path)
        if args.csv:
            export_batch_csv(result, args.csv)
    elif args.command == "gui":
        from .ui.main_window import main as gui_main
        return gui_main([])
    else:
        return 2
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if getattr(args, "output", None):
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

