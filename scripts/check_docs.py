"""Validate local Markdown file links, fenced blocks, and JSON examples."""

import json
import re
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [root / "README.md", root / "CONTRIBUTING.md", *sorted((root / "docs").rglob("*.md"))]
    errors = []
    for file in files:
        text = file.read_text()
        if text.count("```") % 2:
            errors.append(f"{file.relative_to(root)}: unbalanced code fences")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("https://", "http://", "#", "mailto:")):
                continue
            target = target.split("#", 1)[0]
            if target and not (file.parent / target).exists():
                errors.append(f"{file.relative_to(root)}: missing link {target}")
    for file in (root / "docs/examples").glob("*.json"):
        try:
            json.loads(file.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f"{file.relative_to(root)}: {exc}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Document checks passed for {len(files)} Markdown files and JSON examples.")


if __name__ == "__main__":
    main()
