"""Deterministic section-reference parsing and catalog resolution."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ALIAS_VERSION = "section-aliases-v1"

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "摘要"),
    "introduction": ("introduction", "intro", "引言", "绪论"),
    "related_work": (
        "related work",
        "literature review",
        "prior work",
        "相关工作",
        "文献综述",
    ),
    "methods": (
        "methods",
        "method",
        "methodology",
        "materials and methods",
        "research methods",
        "方法",
        "研究方法",
        "材料与方法",
    ),
    "dataset": ("dataset", "data set", "data", "数据集"),
    "model_architecture": (
        "model architecture",
        "model design",
        "模型架构",
        "模型结构",
    ),
    "training_strategy": (
        "training strategy",
        "training procedure",
        "training",
        "训练策略",
        "训练过程",
    ),
    "experiments": (
        "experiments",
        "experiment",
        "experimental evaluation",
        "实验",
    ),
    "experimental_setup": (
        "experimental setup",
        "experiment setup",
        "evaluation setup",
        "实验设置",
    ),
    "results": (
        "results",
        "result",
        "results and findings",
        "findings",
        "结果",
        "主要发现",
    ),
    "discussion": ("discussion", "讨论"),
    "conclusion": ("conclusion", "conclusions", "结论"),
    "references": ("references", "bibliography", "参考文献"),
    "appendix": (
        "appendix",
        "supplement",
        "supplementary material",
        "附录",
        "补充材料",
    ),
}

_NUMBER_VALUE = r"(?:[A-Z]|[IVXLCDM]+|\d+)(?:\s*\.\s*\d+)*"
_CHINESE_NUMBER = re.compile(
    rf"第\s*(?P<number>{_NUMBER_VALUE})\s*(?:章|节|部分)",
    re.IGNORECASE,
)
_ENGLISH_NUMBER = re.compile(
    rf"\b(?:section|sec(?:tion)?\.?|chapter)\s*(?P<number>{_NUMBER_VALUE})\b",
    re.IGNORECASE,
)
_APPENDIX_NUMBER = re.compile(
    r"(?:\bappendix\b|附录)\s*(?P<number>[A-Z](?:\s*\.\s*\d+)*)",
    re.IGNORECASE,
)
_BARE_NUMBER_MARKED = re.compile(
    r"(?<![\w.])(?P<number>\d+(?:\s*\.\s*\d+)+|[A-Z]\s*\.\s*\d+)"
    r"\s*(?:章|节|部分)",
    re.IGNORECASE,
)
_BARE_NUMBER_TITLE = re.compile(
    r"(?<![\w.])(?P<number>\d+(?:\s*\.\s*\d+)+|[A-Z]\s*\.\s*\d+)"
    r"\s+(?P<title>[A-Za-z][A-Za-z0-9 &'_/-]{1,79})",
)
_ENGLISH_TITLE_SECTION = re.compile(
    r"(?P<title>[A-Za-z][A-Za-z0-9 &'_/-]{1,79}?)\s+"
    r"(?:section|chapter)\b",
    re.IGNORECASE,
)
_CHINESE_TITLE_SECTION = re.compile(
    r"(?P<title>[\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z0-9 ]{0,30}?)"
    r"(?:部分|章节)",
)
_CURRENT_DEICTIC = re.compile(r"(?:这一|本|当前)(?:节|章|部分|章节)")
_PREVIOUS_DEICTIC = re.compile(r"(?:上一|前一)(?:节|章|部分|章节)")
_SUMMARY_TERMS = (
    "总结",
    "概括",
    "概述",
    "主要讲",
    "summarize",
    "summary",
    "overview",
)
_PREFIXES = (
    "请解释",
    "请总结",
    "给我讲一下",
    "解释",
    "总结",
    "概括",
    "概述",
    "介绍",
    "说明",
    "explain the ",
    "explain ",
    "summarize the ",
    "summarize ",
    "overview of the ",
    "overview of ",
    "what is in the ",
    "what does the ",
)


class SectionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["number", "title", "deictic", "none"]
    number: str | None = None
    title: str | None = None
    raw_text: str | None = None
    requested_mode: Literal["qa", "summary"] = "qa"
    confidence: float = Field(ge=0, le=1)
    deictic: Literal["current", "previous"] | None = None


class SectionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: str
    document_id: str
    file_id: str
    number: str | None
    title: str
    normalized_title: str = ""
    section_path: list[str] = Field(default_factory=list)
    parent_section_id: str | None = None
    ordinal: int = Field(ge=0)


class SectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_section_id: str
    previous_section_id: str | None = None


class SectionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: SectionRecord
    score: float = Field(ge=0, le=1)
    match_kind: str


class SectionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["resolved", "ambiguous", "unresolved"]
    reference: SectionReference
    selected: SectionRecord | None = None
    candidates: list[SectionCandidate] = Field(default_factory=list)
    match_kind: str | None = None
    reason: str | None = None
    clarification_question: str | None = None


class SectionReferenceParser:
    """Extract explicit section references without asking a model to invent IDs."""

    def parse(self, query: str) -> SectionReference:
        text = unicodedata.normalize("NFKC", query).strip()
        lower = text.casefold()
        mode: Literal["qa", "summary"] = (
            "summary"
            if any(term in lower for term in _SUMMARY_TERMS)
            else "qa"
        )
        if _PREVIOUS_DEICTIC.search(text):
            return SectionReference(
                kind="deictic",
                raw_text=_PREVIOUS_DEICTIC.search(text).group(0),  # type: ignore[union-attr]
                requested_mode=mode,
                confidence=1,
                deictic="previous",
            )
        if _CURRENT_DEICTIC.search(text):
            return SectionReference(
                kind="deictic",
                raw_text=_CURRENT_DEICTIC.search(text).group(0),  # type: ignore[union-attr]
                requested_mode=mode,
                confidence=1,
                deictic="current",
            )

        number_match = (
            _CHINESE_NUMBER.search(text)
            or _ENGLISH_NUMBER.search(text)
            or _APPENDIX_NUMBER.search(text)
            or _BARE_NUMBER_MARKED.search(text)
        )
        if number_match:
            number = normalize_section_number(number_match.group("number"))
            title = _title_after_number(text[number_match.end() :])
            raw = number_match.group(0)
            return SectionReference(
                kind="number",
                number=number,
                title=title,
                raw_text=f"{raw} {title}".strip() if title else raw,
                requested_mode=mode,
                confidence=1,
            )

        bare_match = _BARE_NUMBER_TITLE.search(text)
        if bare_match:
            title = _clean_title(bare_match.group("title"))
            return SectionReference(
                kind="number",
                number=normalize_section_number(bare_match.group("number")),
                title=title,
                raw_text=f"{bare_match.group('number')} {title}".strip(),
                requested_mode=mode,
                confidence=0.99,
            )

        explicit_title = _explicit_title(text)
        if explicit_title:
            return SectionReference(
                kind="title",
                title=explicit_title,
                raw_text=explicit_title,
                requested_mode=mode,
                confidence=0.97,
            )

        alias = _referenced_alias(text)
        if alias:
            return SectionReference(
                kind="title",
                title=alias,
                raw_text=alias,
                requested_mode=mode,
                confidence=0.93,
            )
        return SectionReference(
            kind="none",
            requested_mode=mode,
            confidence=1,
        )


class SectionResolver:
    """Resolve a parsed reference against an already workspace/file-scoped catalog."""

    alias_version = ALIAS_VERSION

    def __init__(
        self,
        *,
        fuzzy_threshold: float = 0.92,
        ambiguity_margin: float = 0.06,
    ) -> None:
        self._fuzzy_threshold = fuzzy_threshold
        self._ambiguity_margin = ambiguity_margin

    def resolve(
        self,
        reference: SectionReference,
        sections: list[SectionRecord],
        *,
        context: SectionContext | None = None,
    ) -> SectionResolution:
        if reference.kind == "none":
            return _unresolved(reference, "no_section_reference")
        if reference.kind == "deictic":
            return self._resolve_deictic(reference, sections, context)
        if reference.number:
            return self._resolve_number(reference, sections)
        if reference.title:
            return self._resolve_title(reference, sections)
        return _unresolved(reference, "section_not_found")

    def _resolve_number(
        self,
        reference: SectionReference,
        sections: list[SectionRecord],
    ) -> SectionResolution:
        target = normalize_section_number(reference.number or "")
        matches = [
            section
            for section in sections
            if section.number is not None
            and normalize_section_number(section.number) == target
        ]
        if not matches:
            return _unresolved(reference, "section_number_not_found")
        if len(matches) == 1:
            return _resolved(reference, matches[0], 1, "number_exact")
        if reference.title:
            title = normalize_section_title(reference.title)
            title_matches = [
                section
                for section in matches
                if normalize_section_title(_section_title(section)) == title
            ]
            if len(title_matches) == 1:
                return _resolved(
                    reference, title_matches[0], 1, "number_title_exact"
                )
        return _ambiguous(
            reference,
            [
                SectionCandidate(
                    section=section,
                    score=1,
                    match_kind="number_exact",
                )
                for section in matches
            ],
        )

    def _resolve_title(
        self,
        reference: SectionReference,
        sections: list[SectionRecord],
    ) -> SectionResolution:
        target = normalize_section_title(reference.title or "")
        exact = [
            section
            for section in sections
            if normalize_section_title(_section_title(section)) == target
        ]
        if exact:
            return _unique_or_ambiguous(reference, exact, 1, "title_exact")

        target_alias = canonical_section_alias(target)
        if target_alias:
            aliases = [
                section
                for section in sections
                if canonical_section_alias(
                    normalize_section_title(_section_title(section))
                )
                == target_alias
            ]
            if aliases:
                return _unique_or_ambiguous(reference, aliases, 0.98, "alias_exact")

        scored = sorted(
            (
                SectionCandidate(
                    section=section,
                    score=_title_similarity(
                        target,
                        normalize_section_title(_section_title(section)),
                    ),
                    match_kind="title_fuzzy",
                )
                for section in sections
            ),
            key=lambda candidate: (
                -candidate.score,
                candidate.section.file_id,
                candidate.section.ordinal,
                candidate.section.section_id,
            ),
        )
        candidates = scored[:3]
        if not candidates or candidates[0].score < self._fuzzy_threshold:
            return _unresolved(
                reference,
                "section_not_found",
                candidates=candidates,
            )
        close = [
            candidate
            for candidate in candidates
            if candidates[0].score - candidate.score <= self._ambiguity_margin
        ]
        if len(close) > 1:
            return _ambiguous(reference, close)
        return SectionResolution(
            status="resolved",
            reference=reference,
            selected=candidates[0].section,
            candidates=[candidates[0]],
            match_kind="title_fuzzy",
        )

    @staticmethod
    def _resolve_deictic(
        reference: SectionReference,
        sections: list[SectionRecord],
        context: SectionContext | None,
    ) -> SectionResolution:
        if context is None:
            return _unresolved(reference, "missing_section_context")
        by_id = {section.section_id: section for section in sections}
        current = by_id.get(context.current_section_id)
        if current is None:
            return _unresolved(reference, "section_context_not_in_catalog")
        if reference.deictic == "current":
            return _resolved(reference, current, 1, "deictic_current")
        if context.previous_section_id:
            previous = by_id.get(context.previous_section_id)
            if previous is not None:
                return _resolved(reference, previous, 1, "deictic_previous")
        previous_sections = [
            section
            for section in sections
            if section.file_id == current.file_id and section.ordinal < current.ordinal
        ]
        if not previous_sections:
            return _unresolved(reference, "previous_section_not_found")
        previous = max(previous_sections, key=lambda section: section.ordinal)
        return _resolved(reference, previous, 1, "deictic_previous")


def normalize_section_number(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    normalized = re.sub(
        r"^(?:SECTION|SEC(?:TION)?\.?|CHAPTER)\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"^第|\s*(?:章|节|部分)$", "", normalized)
    parts = [part.strip() for part in normalized.split(".") if part.strip()]
    return ".".join(str(int(part)) if part.isdigit() else part for part in parts)


def normalize_section_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(
        rf"^(?:section|sec(?:tion)?\.?|chapter)\s+{_NUMBER_VALUE}\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"^第\s*" + _NUMBER_VALUE + r"\s*(?:章|节)\s*", "", normalized)
    normalized = re.sub(
        r"^(?:\d+(?:\.\d+)*|[ivxlcdm]+|[a-z](?:\.\d+)*)\s+(?=\S)",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[_\-/]+", " ", normalized)
    normalized = re.sub(r"[^\w\u3400-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())


def canonical_section_alias(normalized_title: str) -> str | None:
    title = normalize_section_title(normalized_title)
    for canonical, aliases in SECTION_ALIASES.items():
        if title in {normalize_section_title(alias) for alias in aliases}:
            return canonical
    return None


def _explicit_title(text: str) -> str | None:
    candidate_text = _strip_prefix(text)
    english = _ENGLISH_TITLE_SECTION.search(candidate_text)
    if english:
        return _clean_title(english.group("title"))
    chinese = _CHINESE_TITLE_SECTION.search(candidate_text)
    if chinese:
        return _clean_title(chinese.group("title"))
    return None


def _referenced_alias(text: str) -> str | None:
    lower = unicodedata.normalize("NFKC", text).casefold()
    candidates = sorted(
        (
            alias
            for aliases in SECTION_ALIASES.values()
            for alias in aliases
            if normalize_section_title(alias) in normalize_section_title(lower)
        ),
        key=len,
        reverse=True,
    )
    if not candidates:
        return None
    alias = candidates[0]
    alias_normalized = normalize_section_title(alias)
    request_normalized = normalize_section_title(_strip_prefix(text))
    begins_with_alias = request_normalized.startswith(alias_normalized)
    if begins_with_alias:
        return alias
    return None


def _title_after_number(remainder: str) -> str | None:
    clean = remainder.strip(" ：:-")
    if not clean or clean.startswith(("的", "讲", "中", "里", "用")):
        return None
    clean = re.split(r"[?？。！!,，;；:：]", clean, maxsplit=1)[0]
    return _clean_title(clean) or None


def _clean_title(value: str) -> str:
    cleaned = value.strip(" ：:-?？。！!,，;；")
    cleaned = re.sub(
        r"\b(?:used|uses|say|says|describe|describes)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _strip_prefix(value: str) -> str:
    stripped = value.strip()
    lower = stripped.casefold()
    for prefix in _PREFIXES:
        if lower.startswith(prefix.casefold()):
            return stripped[len(prefix) :].strip()
    return stripped


def _section_title(section: SectionRecord) -> str:
    return section.normalized_title or section.title


def _title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0
    sequence = SequenceMatcher(None, left, right).ratio()
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    token_overlap = len(left_tokens & right_tokens) / max(
        1, len(left_tokens | right_tokens)
    )
    compact = SequenceMatcher(
        None,
        left.replace(" ", ""),
        right.replace(" ", ""),
    ).ratio()
    return max(sequence, compact, token_overlap)


def _resolved(
    reference: SectionReference,
    section: SectionRecord,
    score: float,
    match_kind: str,
) -> SectionResolution:
    candidate = SectionCandidate(
        section=section,
        score=score,
        match_kind=match_kind,
    )
    return SectionResolution(
        status="resolved",
        reference=reference,
        selected=section,
        candidates=[candidate],
        match_kind=match_kind,
    )


def _unique_or_ambiguous(
    reference: SectionReference,
    sections: list[SectionRecord],
    score: float,
    match_kind: str,
) -> SectionResolution:
    if len(sections) == 1:
        return _resolved(reference, sections[0], score, match_kind)
    return _ambiguous(
        reference,
        [
            SectionCandidate(
                section=section,
                score=score,
                match_kind=match_kind,
            )
            for section in sections
        ],
    )


def _ambiguous(
    reference: SectionReference,
    candidates: list[SectionCandidate],
) -> SectionResolution:
    labels = [
        f"{candidate.section.number or '无编号'} {candidate.section.title}".strip()
        for candidate in candidates[:3]
    ]
    return SectionResolution(
        status="ambiguous",
        reference=reference,
        candidates=candidates,
        reason="multiple_section_candidates",
        clarification_question="你指的是哪一个章节：" + "；".join(labels) + "？",
    )


def _unresolved(
    reference: SectionReference,
    reason: str,
    *,
    candidates: list[SectionCandidate] | None = None,
) -> SectionResolution:
    return SectionResolution(
        status="unresolved",
        reference=reference,
        candidates=candidates or [],
        reason=reason,
    )
