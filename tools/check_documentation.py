"""Check local Markdown file targets without fetching external links.

Fenced examples, remote URLs and fragment-only links are excluded. This checks
file existence and filename case, not external availability or heading anchors.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXCLUDED = {".git", ".venv", "work", "build", "dist", "__pycache__"}


def check(root: Path):
    problems = []
    files = []
    for directory, children, filenames in os.walk(root):
        children[:] = [name for name in children if name not in EXCLUDED and not name.endswith(".egg-info")]
        files.extend(Path(directory) / name for name in filenames)
    names = {str(p.relative_to(root)).replace("\\", "/"): p for p in files}
    lower = {name.casefold(): name for name in names}
    for name, path in names.items():
        if path.suffix.lower() != ".md":
            continue
        fenced = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            for match in re.finditer(r"!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)", line):
                raw = match.group(1).strip("<>")
                target = urlsplit(raw)
                if target.scheme or target.netloc or not target.path:
                    continue
                resolved = (root / unquote(target.path).lstrip("/") if target.path.startswith("/")
                            else path.parent / unquote(target.path)).resolve()
                try:
                    key = resolved.relative_to(root.resolve()).as_posix()
                except ValueError:
                    problems.append(dict(file=name, line=number, target=raw, reason="outside repository"))
                    continue
                if key not in names and not resolved.is_dir():
                    problems.append(dict(file=name, line=number, target=raw,
                                         reason="filename case" if key.casefold() in lower else "missing file"))
    return problems


if __name__ == "__main__":
    issues = check(Path(__file__).resolve().parents[1])
    print(json.dumps({"local_markdown_link_issues": issues}, indent=2))
    raise SystemExit(bool(issues))
