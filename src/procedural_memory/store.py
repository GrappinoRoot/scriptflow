# =========================
# STORE - where skills live
# =========================
# A store holds Skill objects by intent. Two are included: FileStore (one JSON file per
# skill, human-readable, safe against concurrent writers) and MemoryStore (tests,
# serverless, ephemeral agents). Anything else (Redis, SQL, S3) is a class with the same
# four methods: SkillStore is a Protocol, so no inheritance is needed.
#
# Procedural memory is an optimization and must never break the agent: a missing,
# unreadable or corrupted skill is reported in the log and treated as "no skill".
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from .compiler import VALID_INTENT
from .types import Skill

log = logging.getLogger("procedural_memory")


@runtime_checkable
class SkillStore(Protocol):
    def all(self) -> list[Skill]:
        """Every registered skill."""
        ...

    def get(self, intent: str) -> Skill | None:
        """The skill for this intent (case-insensitive), or None."""
        ...

    def save(self, skill: Skill) -> None:
        """Creates or replaces the skill for skill.intent."""
        ...

    def delete(self, intent: str) -> bool:
        """Removes the skill; True when there was one."""
        ...


def _key(intent: str) -> str:
    key = str(intent).strip().lower()
    if not VALID_INTENT.match(key):
        raise ValueError(f"invalid intent {intent!r}: expected snake_case like 'create_task'")
    return key


class MemoryStore:
    """Keeps skills in a dict. Nothing survives the process."""

    def __init__(self) -> None:
        self._skills: dict[str, dict[str, object]] = {}

    def all(self) -> list[Skill]:
        return [Skill.from_dict(data) for _, data in sorted(self._skills.items())]

    def get(self, intent: str) -> Skill | None:
        try:
            data = self._skills.get(_key(intent))
        except ValueError:
            return None
        return Skill.from_dict(data) if data else None

    def save(self, skill: Skill) -> None:
        # Stored as JSON-shaped data, so callers never share mutable state with the store
        self._skills[_key(skill.intent)] = json.loads(json.dumps(skill.to_dict()))

    def delete(self, intent: str) -> bool:
        try:
            return self._skills.pop(_key(intent), None) is not None
        except ValueError:
            return False


class FileStore:
    """
    One `<intent>.json` file per skill inside `root`. Writes are atomic (temporary file +
    rename), so a reader never sees a half-written skill and a crash never corrupts one.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def _path(self, intent: str) -> Path:
        return self.root / f"{_key(intent)}.json"

    def _read(self, path: Path) -> Skill | None:
        try:
            with path.open(encoding="utf-8") as handle:
                return Skill.from_dict(json.load(handle))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            log.warning("procedural-memory: ignoring unreadable skill %s (%s)", path, error)
            return None

    def all(self) -> list[Skill]:
        if not self.root.is_dir():
            return []
        skills = (self._read(path) for path in sorted(self.root.glob("*.json")))
        return [skill for skill in skills if skill is not None]

    def get(self, intent: str) -> Skill | None:
        try:
            path = self._path(intent)
        except ValueError:
            return None
        return self._read(path)

    def save(self, skill: Skill) -> None:
        path = self._path(skill.intent)
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=f".{path.stem}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(skill.to_dict(), handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def delete(self, intent: str) -> bool:
        try:
            self._path(intent).unlink()
            return True
        except (FileNotFoundError, ValueError):
            return False
