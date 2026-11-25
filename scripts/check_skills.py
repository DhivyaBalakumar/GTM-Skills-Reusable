#!/usr/bin/env python3
"""Validate every skills/*/SKILL.md has frontmatter with name (== folder) and description."""
import pathlib, re, sys

root = pathlib.Path(__file__).resolve().parents[1] / "skills"
bad = []
for skill in sorted(p for p in root.iterdir() if p.is_dir()):
    md = skill / "SKILL.md"
    if not md.exists():
        bad.append(f"{skill.name}: missing SKILL.md"); continue
    m = re.match(r"^---\n(.*?)\n---\n", md.read_text(), re.S)
    if not m:
        bad.append(f"{skill.name}: no frontmatter"); continue
    fm = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
    if fm.get("name") != skill.name:
        bad.append(f"{skill.name}: name '{fm.get('name')}' != folder")
    if not fm.get("description") or len(fm["description"]) > 1024:
        bad.append(f"{skill.name}: description missing or > 1024 chars")
    print(f"ok  {skill.name}" if not any(b.startswith(skill.name) for b in bad) else f"BAD {skill.name}")
if bad:
    print("\n".join(bad)); sys.exit(1)
