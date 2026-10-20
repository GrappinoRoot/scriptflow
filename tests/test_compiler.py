from datetime import datetime, timezone

from conftest import text

from procedural_memory import RegexIdentifiers, compile_procedure
from procedural_memory.recorder import Recorder


def trace(*steps, message="request", answer="done"):
    recorder = Recorder(message)
    for step in steps:
        recorder.record_tool_call(*step)
    recorder.record_final_answer(answer)
    return recorder.trace()


FIND = (
    "find_records",
    {"filter": "name = 'alpha'"},
    True,
    text({"rows": [{"id": "R1a2b3c4d5e6f"}]}),
)


def test_parameters_references_and_constants():
    result = compile_procedure(
        "create_note_for_record",
        {"name": "alpha", "title": "Follow up"},
        trace(
            FIND,
            ("create_record", {"kind": "note", "parent_id": "R1a2b3c4d5e6f", "title": "Follow up"}, True, None),
        ),
        now=lambda: datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    assert result.ok, result.reason
    skill = result.skill
    assert skill.parameters == ["name", "title"]
    assert skill.tools == ["find_records", "create_record"]
    assert skill.steps[0].args == {"filter": "name = '{{name}}'"}
    assert skill.steps[1].args == {
        "kind": "note",
        "parent_id": {"$from": {"step": 0, "path": "rows.0.id"}},
        "title": "{{title}}",
    }
    assert skill.created_at == "2026-10-19T00:00:00.000Z"


def test_identifier_inside_a_larger_string_becomes_a_reference():
    result = compile_procedure(
        "archive_record",
        {"name": "alpha"},
        trace(FIND, ("update_records", {"statement": "set archived = true where id = 'R1a2b3c4d5e6f'"}, True, None)),
    )
    assert result.ok, result.reason
    assert result.skill.steps[1].args["statement"] == "set archived = true where id = '{{@0.rows.0.id}}'"


def test_identifier_from_nowhere_fails():
    result = compile_procedure(
        "archive_record", {}, trace(("update_records", {"statement": "where id = 'R0rphan0000x9'"}, True, None))
    )
    assert not result.ok
    assert "R0rphan0000x9" in result.reason


def test_custom_identifier_rule():
    rules = RegexIdentifiers(r"\bREF-\d+\b")
    result = compile_procedure(
        "close_ref", {}, trace(("close", {"ref": "close REF-123"}, True, None)), identifiers=rules
    )
    assert not result.ok and "REF-123" in result.reason


def test_unused_parameter_fails():
    result = compile_procedure("list_records", {"group": "east"}, trace(("list", {"limit": 5}, True, None)))
    assert not result.ok
    assert "group" in result.reason


def test_failed_steps_are_dropped_and_indexes_stay_consistent():
    result = compile_procedure(
        "create_note_for_record",
        {"name": "alpha"},
        trace(
            ("find_recrods", {"filter": "typo"}, False, "unknown tool"),
            FIND,
            ("create_record", {"parent_id": "R1a2b3c4d5e6f"}, True, None),
        ),
    )
    assert result.ok, result.reason
    assert [s.tool for s in result.skill.steps] == ["find_records", "create_record"]
    assert result.skill.steps[1].args["parent_id"] == {"$from": {"step": 0, "path": "rows.0.id"}}


def test_numbers():
    result = compile_procedure(
        "move_point",
        {"place": "north"},
        trace(
            ("locate", {"place": "north"}, True, text({"x": 45.07, "y": 7.69, "count": 3, "dup": [500, 500]})),
            ("move", {"x": 45.07, "y": 7.69, "limit": 3, "dup": 500, "visible": True}, True, None),
        ),
    )
    assert result.ok, result.reason
    args = result.skill.steps[1].args
    assert args["x"] == {"$from": {"step": 0, "path": "x"}}
    assert args["limit"] == 3  # small integers stay constant
    assert args["dup"] == 500  # ambiguous: appears twice
    assert args["visible"] is True  # booleans are flags of the procedure


def test_values_from_a_request_independent_step_stay_literal():
    # A step without parameters returns the same thing every run: a constant that happens to
    # appear in its result ("note" inside a schema) must stay a constant, not a fragile link.
    schema = text({"fields": [{"name": "title", "kind": "note"}], "max_length": 250})
    result = compile_procedure(
        "create_note",
        {"title": "Follow up"},
        trace(
            ("get_schema", {"kind": "note"}, True, schema),
            ("create_record", {"kind": "note", "title": "Follow up", "max_length": 250}, True, None),
        ),
    )
    assert result.ok, result.reason
    assert result.skill.steps[1].args == {"kind": "note", "title": "{{title}}", "max_length": 250}


def test_identifiers_are_linked_even_from_a_request_independent_step():
    result = compile_procedure(
        "create_note",
        {"title": "Follow up"},
        trace(
            ("whoami", {}, True, text({"user_id": "U5k4j3h2g1f0e"})),
            ("create_record", {"owner_id": "U5k4j3h2g1f0e", "title": "Follow up"}, True, None),
        ),
    )
    assert result.ok, result.reason
    assert result.skill.steps[1].args["owner_id"] == {"$from": {"step": 0, "path": "user_id"}}


def test_a_fragment_of_a_parameter_refuses_the_skill():
    # The agent turned "Alpha Beta Gamma" into "%Beta%" and took the id from that search.
    # Replayed for another name, the skill would still search "%Beta%" and act on the wrong record.
    found = text({"rows": [{"id": "R1a2b3c4d5e6f", "name": "Alpha Beta Gamma Ltd."}]})
    result = compile_procedure(
        "create_note_for_record",
        {"title": "Follow up", "name": "Alpha Beta Gamma"},
        trace(
            ("find_records", {"filter": "name = 'Alpha Beta Gamma'"}, True, text({"rows": []})),
            ("find_records", {"filter": "name like '%Beta%'"}, True, found),
            ("create_record", {"title": "Follow up", "parent_id": "R1a2b3c4d5e6f"}, True, None),
        ),
    )
    assert not result.ok
    assert "'beta'" in result.reason and "name" in result.reason


def test_the_whole_parameter_next_to_its_own_words_is_fine():
    result = compile_procedure(
        "find_record",
        {"name": "Records Archive"},
        trace(("find_records", {"filter": "type = records and name = 'Records Archive'"}, True, None)),
    )
    assert result.ok, result.reason
    assert result.skill.steps[0].args["filter"] == "type = records and name = '{{name}}'"


def test_boolean_parameter_never_matches_one():
    result = compile_procedure("toggle", {"on": True}, trace(("set", {"count": 1, "enabled": True}, True, None)))
    assert result.ok, result.reason
    assert result.skill.steps[0].args == {"count": 1, "enabled": "{{on}}"}


def test_parameters_match_whole_tokens_only():
    result = compile_procedure(
        "find_code", {"code": "AB"}, trace(("find", {"q": "find AB in TABLE_ABC or ABx"}, True, None))
    )
    assert result.ok, result.reason
    assert result.skill.steps[0].args["q"] == "find {{code}} in TABLE_ABC or ABx"


def test_longest_parameter_wins_and_placeholders_are_not_rewritten():
    result = compile_procedure(
        "rename",
        {"short": "Alpha", "full": "Alpha One", "word": "full"},
        trace(("rename", {"from": "Alpha One", "to": "Alpha", "mode": "full"}, True, None)),
    )
    assert result.ok, result.reason
    assert result.skill.steps[0].args == {"from": "{{full}}", "to": "{{short}}", "mode": "{{word}}"}


def test_invalid_intent_and_empty_trace():
    assert not compile_procedure("Not Valid", {}, trace(FIND)).ok
    assert "no successful step" in compile_procedure("x", {}, trace(("a", {}, False, None))).reason
