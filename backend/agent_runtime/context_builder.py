"""Profile-aware context assembly with traceable retrieval sources."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ContextSource:
    source_id: str
    content: str

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id is required for retrieved context")


@dataclass(frozen=True, slots=True)
class ContextInput:
    system_policy: str
    requirement_brief: str
    skill_instructions: str
    tool_schemas: str
    plan: str
    recent_messages: list[str] = field(default_factory=list)
    memory: list[ContextSource] = field(default_factory=list)
    workspace: list[ContextSource] = field(default_factory=list)
    rag_evidence: list[ContextSource] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BuiltContext:
    text: str
    estimated_tokens: int
    source_ids: set[str]
    truncated: bool


class ContextBuilder:
    """Keeps policy/requirements first and drops lower-priority tails."""

    def build(
        self,
        item: ContextInput,
        *,
        context_length: int,
        reserved_output_tokens: int,
    ) -> BuiltContext:
        budget = context_length - reserved_output_tokens
        if budget <= 0:
            raise ValueError("reserved output tokens must be below context length")
        required = [
            ("SYSTEM POLICY", item.system_policy),
            ("REQUIREMENT BRIEF", item.requirement_brief),
            ("SKILL", item.skill_instructions),
            ("TOOLS", item.tool_schemas),
            ("PLAN", item.plan),
        ]
        optional = [
            ("RECENT MESSAGES", "\n".join(item.recent_messages), None),
            *self._source_sections("RAG EVIDENCE", item.rag_evidence),
            *self._source_sections("WORKSPACE", item.workspace),
            *self._source_sections("MEMORY", item.memory),
        ]
        sections = [self._format(title, text) for title, text in required if text]
        source_ids: set[str] = set()
        truncated = False
        if self._tokens("\n".join(sections)) > budget:
            text = "\n".join(sections)
            allowed_chars = max(1, budget * 4)
            return BuiltContext(text[:allowed_chars], self._tokens(text[:allowed_chars]), set(), True)
        for title, content, source_id in optional:
            if not content:
                continue
            section = self._format(title, content)
            candidate = "\n".join([*sections, section])
            if self._tokens(candidate) > budget:
                truncated = True
                continue
            sections.append(section)
            if source_id:
                source_ids.add(source_id)
        text = "\n".join(sections)
        return BuiltContext(text, self._tokens(text), source_ids, truncated)

    @staticmethod
    def _source_sections(
        title: str,
        sources: list[ContextSource],
    ) -> list[tuple[str, str, str]]:
        return [
            (title, f"[source:{source.source_id}]\n{source.content}", source.source_id)
            for source in sources
        ]

    @staticmethod
    def _format(title: str, content: str) -> str:
        return f"## {title}\n{content}"

    @staticmethod
    def _tokens(text: str) -> int:
        return (len(text) + 3) // 4
