import json
import logging

import pytest

from procedural_memory import FileStore, MemoryStore, Skill, SkillStep


def skill(intent="find_thing", runs=0):
    s = Skill(intent=intent, parameters=["name"], steps=[SkillStep("find", {"q": "{{name}}"})], description="d")
    s.stats.runs = runs
    return s


@pytest.fixture(params=["file", "memory"])
def store(request, tmp_path):
    return FileStore(tmp_path / "skills") if request.param == "file" else MemoryStore()


def test_roundtrip(store):
    assert store.all() == []
    store.save(skill())
    assert store.get("FIND_THING") == skill()
    assert [s.intent for s in store.all()] == ["find_thing"]
    store.save(skill(runs=3))
    assert store.get("find_thing").stats.runs == 3
    assert store.delete("find_thing")
    assert not store.delete("find_thing")
    assert store.get("find_thing") is None


def test_invalid_intents(store):
    assert store.get("../etc/passwd") is None
    assert not store.delete("../x")
    with pytest.raises(ValueError):
        store.save(skill(intent="../escape"))


def test_memory_store_does_not_share_state():
    store = MemoryStore()
    original = skill()
    store.save(original)
    original.steps[0].args["q"] = "changed"
    store.get("find_thing").steps[0].args["q"] = "changed too"
    assert store.get("find_thing").steps[0].args == {"q": "{{name}}"}


def test_file_store_layout_and_corruption(tmp_path, caplog):
    store = FileStore(tmp_path)
    store.save(skill())
    data = json.loads((tmp_path / "find_thing.json").read_text())
    assert data["format"] == 1 and data["tools"] == ["find"]
    assert list(tmp_path.glob(".*.tmp")) == []

    (tmp_path / "broken.json").write_text("{ not json")
    (tmp_path / "future.json").write_text(json.dumps({**data, "intent": "future", "format": 2}))
    with caplog.at_level(logging.WARNING, logger="procedural_memory"):
        assert [s.intent for s in store.all()] == ["find_thing"]
    assert "broken.json" in caplog.text and "unsupported skill format" in caplog.text
