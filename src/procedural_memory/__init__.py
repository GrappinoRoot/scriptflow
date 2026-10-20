"""
Procedural memory for LLM agents: record solved tasks, compile them into replayable skills,
run them without reasoning again.

    from procedural_memory import ProceduralMemory

    memory = ProceduralMemory(root="./skills", classify=my_model_call)
    result = await memory.handle(request, call_tool=call_tool, agent=agent)
"""

from .compiler import CompileResult, compile_procedure, find_value_path, find_value_paths
from .identifiers import DEFAULT_IDENTIFIERS, IdentifierRules, RegexIdentifiers
from .intent import (
    DEFAULT_EXAMPLES,
    Example,
    Intent,
    build_intent_prompt,
    extract_intent,
    normalize_parameter_value,
)
from .memory import Agent, ProceduralMemory, Task
from .recorder import Recorder, is_successful_run, successful_steps
from .runtime import (
    SkillParameterError,
    escape_embedded,
    get_at_path,
    parse_tool_content,
    render_args,
    run_skill,
)
from .store import FileStore, MemoryStore, SkillStore
from .types import (
    SKILL_FORMAT,
    CallTool,
    Classify,
    ExecutedStep,
    HandleResult,
    LearnResult,
    RecordedStep,
    RunResult,
    Skill,
    SkillStats,
    SkillStep,
    ToolResult,
    Trace,
    Verdict,
    Verify,
    VerifyContext,
)
from .verify import MUTATION_VERBS, implies_mutation, mutation_verifier

__version__ = "0.3.0"

__all__ = [
    "DEFAULT_EXAMPLES",
    "DEFAULT_IDENTIFIERS",
    "MUTATION_VERBS",
    "SKILL_FORMAT",
    "Agent",
    "CallTool",
    "Classify",
    "CompileResult",
    "Example",
    "ExecutedStep",
    "FileStore",
    "HandleResult",
    "IdentifierRules",
    "Intent",
    "LearnResult",
    "MemoryStore",
    "ProceduralMemory",
    "RecordedStep",
    "Recorder",
    "RegexIdentifiers",
    "RunResult",
    "Skill",
    "SkillParameterError",
    "SkillStats",
    "SkillStep",
    "SkillStore",
    "Task",
    "ToolResult",
    "Trace",
    "Verdict",
    "Verify",
    "VerifyContext",
    "__version__",
    "build_intent_prompt",
    "compile_procedure",
    "escape_embedded",
    "extract_intent",
    "find_value_path",
    "find_value_paths",
    "get_at_path",
    "implies_mutation",
    "is_successful_run",
    "mutation_verifier",
    "normalize_parameter_value",
    "parse_tool_content",
    "render_args",
    "run_skill",
    "successful_steps",
]
