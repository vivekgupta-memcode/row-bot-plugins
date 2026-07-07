from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from _bootstrap_row_bot import bootstrap

sys.dont_write_bytecode = True
bootstrap()

from row_bot.plugins.devtools import build_index, write_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Row-Bot plugin marketplace index.")
    parser.add_argument("root", help="Repository root containing plugins/")
    parser.add_argument("--source", default="")
    parser.add_argument("--check", action="store_true", help="Print the index instead of writing index.json")
    args = parser.parse_args(argv)
    _remove_generated_python_artifacts(Path(args.root).expanduser().resolve())
    if args.check:
        print(json.dumps(build_index(args.root, source=args.source), indent=2))
    else:
        path = write_index(args.root, source=args.source)
        print(path)
    return 0


def _remove_generated_python_artifacts(root: Path) -> None:
    for parent in (root / "plugins", root / "templates"):
        if not parent.is_dir():
            continue
        for cache_dir in parent.rglob("__pycache__"):
            if cache_dir.is_dir():
                shutil.rmtree(cache_dir)
        for pattern in ("*.pyc", "*.pyo", "*.pyd"):
            for path in parent.rglob(pattern):
                if path.is_file():
                    path.unlink()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
