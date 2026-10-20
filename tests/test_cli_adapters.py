import asyncio
import json
from types import SimpleNamespace

from procedural_memory import FileStore
from procedural_memory.adapters import anthropic_classifier, ollama_classifier, openai_classifier
from procedural_memory.cli import main

# What @script-flow/procedural-memory 0.2.x wrote to disk
LEGACY_SCRIPT = """// Skill compiled automatically by @script-flow/procedural-memory: do not edit by hand.
// intent: find_record
import { renderArgs, parseToolContent } from "@script-flow/procedural-memory/runtime";

export const intent = "find_record";
export const parameters = ["name"];
export const tools = ["find_records"];

const STEPS = [
    {
        "tool": "find_records",
        "args": {
            "filter": "name = '{{name}}'"
        }
    }
];

/**
 * Replays the recorded procedure.
 */
export async function run(params, { callTool }) {}
"""


def test_cli_import_list_show_delete(tmp_path, capsys):
    legacy, root = tmp_path / "legacy", tmp_path / "skills"
    legacy.mkdir()
    (legacy / "find_record.mjs").write_text(LEGACY_SCRIPT)
    registry = {
        "skills": [
            {
                "intent": "find_record",
                "description": "Learned from: Find alpha",
                "parameters": ["name"],
                "tools": ["find_records"],
                "script": "find_record.mjs",
                "createdAt": "2026-10-05T09:00:00.000Z",
                "runs": 4,
                "failures": 1,
                "lastRunAt": None,
            },
            {"intent": "lost_skill", "script": "missing.mjs"},
        ]
    }
    (legacy / "registry.json").write_text(json.dumps(registry))

    assert main(["--root", str(root), "import-legacy", str(legacy)]) == 0
    skill = FileStore(root).get("find_record")
    assert skill.steps[0].args == {"filter": "name = '{{name}}'"}
    assert (skill.stats.runs, skill.learned_from) == (4, "Find alpha")
    out = capsys.readouterr()
    assert "imported 1 skill(s)" in out.out and "skipped lost_skill" in out.err

    assert main(["--root", str(root), "list"]) == 0
    assert "find_record(name)  runs=4" in capsys.readouterr().out
    assert main(["--root", str(root), "show", "find_record"]) == 0
    assert json.loads(capsys.readouterr().out)["intent"] == "find_record"
    assert main(["--root", str(root), "delete", "find_record"]) == 0
    assert main(["--root", str(root), "show", "find_record"]) == 1


class Recorder:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_openai_adapter_sync_and_async():
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent": "x"}'))])
    create = Recorder(reply)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert openai_classifier(client, "m", temperature=0)("SYS", "USER") == '{"intent": "x"}'
    assert create.kwargs["messages"][0] == {"role": "system", "content": "SYS"}
    assert create.kwargs["temperature"] == 0

    async def acreate(**kwargs):
        return reply

    aclient = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=acreate)))
    assert asyncio.run(openai_classifier(aclient, "m")("s", "u")) == '{"intent": "x"}'


def test_anthropic_adapter_skips_non_text_blocks():
    reply = SimpleNamespace(content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="{}")])
    create = Recorder(reply)
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    assert anthropic_classifier(client, "claude-opus-5-5")("SYS", "USER") == "{}"
    assert create.kwargs["system"] == "SYS" and create.kwargs["messages"] == [{"role": "user", "content": "USER"}]


def test_ollama_adapter():
    chat = Recorder({"message": {"content": "{}"}})
    assert ollama_classifier(SimpleNamespace(chat=chat), "llama3.1")("s", "u") == "{}"
    assert chat.kwargs["format"] == "json"
