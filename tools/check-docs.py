#!/usr/bin/env python3
"""Read-only documentation checks. Snippets are parsed, never executed."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^```([a-zA-Z0-9_-]*)[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
PYTHON_HEREDOC = re.compile(
    r"^[^\n]*\bpython3?\b[^\n]*<<'(?P<end>[A-Za-z0-9_]+)'\n(?P<body>.*?)^(?P=end)[ \t]*$",
    re.M | re.S,
)


def main() -> int:
    failures = []
    counts = {"markdown": 0, "shell": 0, "python": 0, "json": 0}
    paths = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        label = str(path.relative_to(ROOT))
        counts["markdown"] += 1
        if "同门" in source:
            failures.append(label + ": audience-specific wording")
        if len(re.findall(r"^```", source, re.M)) % 2:
            failures.append(label + ": unbalanced fences")
        for target in re.findall(r"\]\(([^)]+)\)", source):
            if "://" in target or target.startswith("#"):
                continue
            if not (path.parent / target.split("#", 1)[0]).exists():
                failures.append(label + ": missing relative link: " + target)
        for language, code in FENCE.findall(source):
            try:
                if language in ("bash", "sh"):
                    counts["shell"] += 1
                    parsed = subprocess.run(["bash", "-n"], input=code, text=True, capture_output=True)
                    if parsed.returncode:
                        failures.append(label + ": shell syntax: " + parsed.stderr.strip())
                    for heredoc in PYTHON_HEREDOC.finditer(code):
                        ast.parse(heredoc["body"], filename=label)
                        counts["python"] += 1
                elif language == "python":
                    ast.parse(code, filename=label)
                    counts["python"] += 1
                elif language == "json":
                    json.loads(code)
                    counts["json"] += 1
            except (SyntaxError, ValueError) as error:
                failures.append(label + ": " + str(error))
    for path in sorted((ROOT / "examples").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
            counts["json"] += 1
        except ValueError as error:
            failures.append(str(path.relative_to(ROOT)) + ": " + str(error))
    print(json.dumps(counts, sort_keys=True))
    if failures:
        print("\n".join(failures))
        return 1
    print("PASS: links, wording, fences, and snippet syntax; no snippet executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
