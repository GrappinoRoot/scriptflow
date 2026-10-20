# =========================
# CLI - inspect and manage a skills directory
# =========================
#   procedural-memory list                  [--root ./skills]
#   procedural-memory show <intent>         [--root ./skills]
#   procedural-memory delete <intent>       [--root ./skills]
#   procedural-memory import-legacy <dir>   [--root ./skills]   (skills learned by the npm package 0.x)
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .store import FileStore
from .types import Skill, SkillStats, SkillStep

# The generated .mjs scripts of @script-flow/procedural-memory 0.x hold their steps as a JSON
# literal: `const STEPS = [...];` followed by the run() doc comment.
_LEGACY_STEPS = re.compile(r"const STEPS = (\[.*?\]);\s*\n\s*/\*\*", re.DOTALL)


def import_legacy(source: Path, store: FileStore) -> list[str]:
    """Converts a 0.x skills directory (registry.json + <intent>.mjs) into JSON skills."""
    registry = json.loads((source / "registry.json").read_text(encoding="utf-8"))
    imported = []
    for entry in registry.get("skills", []):
        intent = entry.get("intent", "?")
        script = source / str(entry.get("script", f"{intent}.mjs"))
        try:
            match = _LEGACY_STEPS.search(script.read_text(encoding="utf-8"))
            if not match:
                raise ValueError("no STEPS literal found")
            steps = [SkillStep(tool=s["tool"], args=s.get("args", {})) for s in json.loads(match.group(1))]
            description = str(entry.get("description", ""))
            store.save(
                Skill(
                    intent=intent,
                    parameters=list(entry.get("parameters", [])),
                    steps=steps,
                    description=description,
                    learned_from=description.removeprefix("Learned from: "),
                    created_at=str(entry.get("createdAt", "")),
                    stats=SkillStats(
                        runs=int(entry.get("runs", 0) or 0),
                        failures=int(entry.get("failures", 0) or 0),
                        last_run_at=entry.get("lastRunAt"),
                    ),
                )
            )
            imported.append(intent)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"skipped {intent}: {error}", file=sys.stderr)
    return imported


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="procedural-memory", description="Manage a procedural memory skills directory."
    )
    parser.add_argument("--root", default="./skills", help="skills directory (default: ./skills)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the registered skills")
    commands.add_parser("show", help="print a skill as JSON").add_argument("intent")
    commands.add_parser("delete", help="remove a skill").add_argument("intent")
    commands.add_parser("import-legacy", help="import skills learned by the npm package 0.x").add_argument("source")
    args = parser.parse_args(argv)
    store = FileStore(args.root)

    if args.command == "list":
        skills = store.all()
        if not skills:
            print(f"no skills in {args.root}")
        for skill in skills:
            params = ", ".join(skill.parameters)
            print(
                f"{skill.intent}({params})  runs={skill.stats.runs} failures={skill.stats.failures}  {skill.description}"
            )
        return 0
    if args.command == "show":
        found = store.get(args.intent)
        if found is None:
            print(f"no skill named {args.intent}", file=sys.stderr)
            return 1
        _print_json(found.to_dict())
        return 0
    if args.command == "delete":
        if not store.delete(args.intent):
            print(f"no skill named {args.intent}", file=sys.stderr)
            return 1
        print(f"deleted {args.intent}")
        return 0
    imported = import_legacy(Path(args.source), store)
    print(f"imported {len(imported)} skill(s) into {args.root}: {', '.join(imported) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
