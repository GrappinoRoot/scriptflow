import asyncio
import json

from procedural_memory import Example, Skill, SkillStep, build_intent_prompt, extract_intent, normalize_parameter_value


def run(classify, message="Find alpha"):
    return asyncio.run(extract_intent(message, classify))


def test_extracts_and_normalizes():
    reply = {
        "intent": " Find Record ",
        "parameters": {
            "name": '"alpha"',
            "id": "Record R7f3k2m9x1q8z",
            "n": 3,
            "bad key": "x",
            "nested": {"a": 1},
        },
    }
    result = run(lambda system, user: json.dumps(reply))
    assert result.intent == "find_record"
    assert result.parameters == {"name": "alpha", "id": "R7f3k2m9x1q8z", "n": 3}


def test_tolerates_code_fences_and_chatter():
    assert run(lambda s, u: '```json\n{"intent": "a_b", "parameters": {}}\n```').intent == "a_b"
    assert run(lambda s, u: 'Sure! {"intent": "a_b", "parameters": {}} hope it helps').intent == "a_b"


def test_async_classifier():
    async def classify(system, user):
        return '{"intent": "x", "parameters": {"q": "y"}}'

    assert run(classify).parameters == {"q": "y"}


def test_failures_return_none():
    def boom(system, user):
        raise ConnectionError("offline")

    assert run(boom) is None
    assert run(lambda s, u: "no json here") is None
    assert run(lambda s, u: '{"intent": "1bad", "parameters": {}}') is None
    assert run(lambda s, u: '{"intent": "ok", "parameters": []}') is None
    assert run(lambda s, u: '["intent"]') is None
    assert run(lambda s, u: "{}", message="") is None


def test_prompt_lists_known_skills_and_examples():
    known = [Skill("create_note", ["title"], [SkillStep("t", {})], description="Learned from: x")]
    prompt = build_intent_prompt(
        known, "a project tracker", [Example("Close alpha", "close_record", {"name": "alpha"})]
    )
    assert "- create_note(title): Learned from: x" in prompt
    assert "The requests concern a project tracker." in prompt
    assert '{"intent": "close_record", "parameters": {"name": "alpha"}}' in prompt
    assert "(no procedure registered yet)" in build_intent_prompt()


def test_normalize_parameter_value():
    assert normalize_parameter_value("  'quoted'  ") == "quoted"
    assert normalize_parameter_value(7) == 7
