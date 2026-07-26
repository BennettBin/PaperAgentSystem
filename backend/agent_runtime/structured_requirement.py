"""Structured, public requirement contract shared by routing and execution."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TaskType(str, Enum):
    GENERAL_ANSWER = "general_answer"
    DOCUMENT_QA = "document_qa"
    PAPER_DISCOVERY = "paper_discovery"
    ACADEMIC_REWRITE = "academic_rewrite"
    DOCUMENT_SUMMARY = "document_summary"
    PAPER_COMPARISON = "paper_comparison"
    LITERATURE_SYNTHESIS = "literature_synthesis"
    CLAIM_ANALYSIS = "claim_analysis"
    DOCUMENT_PARSE = "document_parse"


class TurnRelation(str, Enum):
    NEW_TASK = "new_task"
    CONTINUE_PREVIOUS = "continue_previous"
    REVISE_PREVIOUS_OUTPUT = "revise_previous_output"
    ANSWER_CLARIFICATION = "answer_clarification"
    UNCERTAIN = "uncertain"


class SourceMode(str, Enum):
    NONE = "none"
    INLINE_TEXT = "inline_text"
    CONVERSATION_MATERIAL = "conversation_material"
    UPLOADED_FILES = "uploaded_files"
    EXTERNAL = "external"


class MemoryMode(str, Enum):
    NONE = "none"
    CONSTRAINTS_ONLY = "constraints_only"
    SPECIFIC_MATERIAL = "specific_material"
    RECENT_CONTEXT = "recent_context"
    CROSS_CONVERSATION = "cross_conversation"


class StructuredRequirement(BaseModel):
    """One-turn decision; contains no hidden reasoning or document body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: TaskType
    turn_relation: TurnRelation = TurnRelation.NEW_TASK
    source_mode: SourceMode = SourceMode.NONE
    memory_mode: MemoryMode = MemoryMode.NONE
    selected_skills: list[str] = Field(default_factory=list, max_length=3)
    primary_skill: str | None = None
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)
    missing_inputs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason_summary: str = Field(default="", max_length=240)


_REWRITE = re.compile(
    r"(?:润色|改写|重写|优化表述|调整表达|语言优化|学术化|衔接|融入|"
    r"polish|rewrite|paraphrase)",
    re.IGNORECASE,
)
_DISCOVERY = re.compile(
    r"(?:检索|查找|搜索|推荐|寻找).{0,12}(?:论文|文献)|"
    r"(?:论文|文献).{0,12}(?:检索|查找|搜索|推荐|寻找)|crossref|arxiv|openalex|semantic scholar",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"(?:继续|接着|刚才|之前|前面|上面|上述|那段|上一版|再润色|再改|"
    r"continue|previous)",
    re.IGNORECASE,
)


def infer_structured_requirement(
    request: str,
    *,
    file_count: int = 0,
    has_inline_text: bool = False,
    has_conversation_material: bool = False,
    pending_clarification: bool = False,
) -> StructuredRequirement:
    """Safe deterministic fallback used only when the small model is unavailable."""

    normalized = request.strip()
    relation = (
        TurnRelation.ANSWER_CLARIFICATION
        if pending_clarification and len(normalized) < 80
        else TurnRelation.CONTINUE_PREVIOUS
        if _FOLLOW_UP.search(normalized)
        else TurnRelation.NEW_TASK
    )
    if _REWRITE.search(normalized):
        source = (
            SourceMode.INLINE_TEXT
            if has_inline_text
            else SourceMode.UPLOADED_FILES
            if file_count
            else SourceMode.CONVERSATION_MATERIAL
            if has_conversation_material
            else SourceMode.NONE
        )
        return StructuredRequirement(
            task_type=TaskType.ACADEMIC_REWRITE,
            turn_relation=relation,
            source_mode=source,
            memory_mode=(
                MemoryMode.SPECIFIC_MATERIAL
                if source is SourceMode.CONVERSATION_MATERIAL
                else MemoryMode.NONE
            ),
            selected_skills=["academic_rewriter"],
            primary_skill="academic_rewriter",
            needs_clarification=source is SourceMode.NONE,
            clarification_questions=(
                [] if source is not SourceMode.NONE else ["请粘贴、上传或明确指出要润色的文本。"]
            ),
            missing_inputs=[] if source is not SourceMode.NONE else ["source_text"],
            confidence=0.92,
            reason_summary="检测到明确的学术文本改写需求",
        )
    if _DISCOVERY.search(normalized):
        return StructuredRequirement(
            task_type=TaskType.PAPER_DISCOVERY,
            turn_relation=relation,
            source_mode=SourceMode.EXTERNAL,
            selected_skills=["paper_discovery"],
            primary_skill="paper_discovery",
            confidence=0.9,
            reason_summary="检测到外部论文检索需求",
        )
    if re.search(r"(?:比较|对比|异同|compare)", normalized, re.IGNORECASE):
        task_type = TaskType.PAPER_COMPARISON
        primary = "comparison_analyzer"
    elif re.search(r"(?:综述|综合多篇|literature review)", normalized, re.IGNORECASE):
        task_type = TaskType.LITERATURE_SYNTHESIS
        primary = "literature_synthesizer"
    elif re.search(r"(?:总结|摘要|概括|summar)", normalized, re.IGNORECASE):
        task_type = TaskType.DOCUMENT_SUMMARY
        primary = "summary_generator"
    elif re.search(r"(?:主张|论断|核验|引用|claim)", normalized, re.IGNORECASE):
        task_type = TaskType.CLAIM_ANALYSIS
        primary = "claim_verifier"
    elif file_count or re.search(r"(?:论文|文章|章节|实验|方法|数据集)", normalized):
        task_type = TaskType.DOCUMENT_QA
        primary = "paper_reader"
    else:
        task_type = TaskType.GENERAL_ANSWER
        primary = "paper_reader"
    source = SourceMode.UPLOADED_FILES if file_count else SourceMode.NONE
    return StructuredRequirement(
        task_type=task_type,
        turn_relation=relation,
        source_mode=source,
        memory_mode=(
            MemoryMode.RECENT_CONTEXT
            if relation is not TurnRelation.NEW_TASK
            else MemoryMode.NONE
        ),
        selected_skills=[primary],
        primary_skill=primary,
        confidence=0.75,
        reason_summary="使用确定性规则完成安全路由",
    )
