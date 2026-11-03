#!/usr/bin/env python3
"""Check an extracted HW03 submission's layout without running student code."""

import argparse
import json
from pathlib import Path
import sys


TEXT_FILES = (
    "q2/Makefile", "q2/src/main.c", "q2/src/run.c", "q2/include/runner.h",
    "q2/answers.md", "q2/test-results.txt",
)
VIDEOS = ("q2/video.mp4",)


def check(root):
    errors = []
    for relative in (*TEXT_FILES, *VIDEOS):
        path = root / relative
        if not path.resolve().is_relative_to(root):
            errors.append(f"{relative}: must be inside the submission directory")
        elif not path.is_file() or path.stat().st_size == 0:
            errors.append(f"{relative}: required nonempty file missing")
        elif relative in TEXT_FILES:
            try:
                path.read_text(encoding="utf-8")
            except UnicodeError:
                errors.append(f"{relative}: must be UTF-8 text")
        else:
            with path.open("rb") as stream:
                header = stream.read(12)
            if len(header) < 12 or header[4:8] != b"ftyp":
                errors.append(f"{relative}: expected an MP4 file header")
    if (root / "q2/langar").exists() or list((root / "q2").rglob("*.o")):
        errors.append("q2: remove the built executable and object files (make clean)")
    if (root / ".git").exists() or (root / "q2/.git").exists():
        errors.append("remove Git metadata from the submission")
    return dict(valid=not errors, errors=errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path, help="directory containing q2/")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    root = args.submission.resolve()
    if not root.is_dir():
        parser.error("submission must be an extracted directory")
    try:
        report = check(root)
    except OSError as exc:
        report = dict(valid=False, errors=[str(exc)])
    for message in report["errors"]:
        print(f"FAIL {message}")
    if report["valid"]:
        print("PASS required layout, nonempty files, UTF-8 text, and MP4 headers")
        print("Content correctness, complete video playback, and explanations require review.")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
