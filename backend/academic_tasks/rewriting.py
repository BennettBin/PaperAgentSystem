"""Invariant-preserving academic rewriting and regression checks."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RewriteMode(str, Enum):
    COMPRESS = "compress"
    EXPAND = "expand"
    POLISH = "polish"
    RESTRUCTURE = "restructure"


class Invariants(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numbers: list[str]
    formulas: list[str]
    citations: list[str]
    terms: list[str]
    propositions: list[str]


class RewriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    mode: RewriteMode
    invariants: Invariants
    change_notes: list[str]
    invariant_preservation: float = Field(ge=0, le=1)
    semantic_score: float = Field(ge=0, le=5)
    academic_style_score: float = Field(ge=0, le=5)
    regression_passed: bool
    missing_invariants: list[str]


class AcademicRewriter:
    NUMBER = re.compile(r"(?<!\w)\d+(?:\.\d+)?%?")
    FORMULA = re.compile(r"\$[^$]+\$|\\\([^)]*\\\)|\\\[[^\]]*\\\]")
    CITATION = re.compile(r"\[[A-Za-z]?\d+(?:[-,]\s*[A-Za-z]?\d+)*\]")

    def extract_invariants(
        self,
        text: str,
        *,
        protected_terms: list[str] | None = None,
    ) -> Invariants:
        propositions = [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？.!?])\s+|\n+", text)
            if sentence.strip()
        ]
        return Invariants(
            numbers=list(dict.fromkeys(self.NUMBER.findall(text))),
            formulas=list(dict.fromkeys(self.FORMULA.findall(text))),
            citations=list(dict.fromkeys(self.CITATION.findall(text))),
            terms=list(dict.fromkeys(protected_terms or [])),
            propositions=propositions,
        )

    def rewrite(
        self,
        text: str,
        mode: RewriteMode,
        *,
        protected_terms: list[str] | None = None,
    ) -> RewriteResult:
        invariants = self.extract_invariants(text, protected_terms=protected_terms)
        rewritten, notes = self._transform(text, mode)
        required = [
            *invariants.numbers,
            *invariants.formulas,
            *invariants.citations,
            *invariants.terms,
        ]
        missing = [item for item in required if item not in rewritten]
        preservation = (len(required) - len(missing)) / max(1, len(required))
        proposition_terms = set(_content_terms(" ".join(invariants.propositions)))
        rewritten_terms = set(_content_terms(rewritten))
        semantic_overlap = len(proposition_terms & rewritten_terms) / max(
            1, len(proposition_terms)
        )
        semantic_score = min(5.0, semantic_overlap * 5)
        style_score = self._style_score(rewritten)
        return RewriteResult(
            text=rewritten,
            mode=mode,
            invariants=invariants,
            change_notes=notes,
            invariant_preservation=preservation,
            semantic_score=semantic_score,
            academic_style_score=style_score,
            regression_passed=not missing and semantic_score >= 4.5,
            missing_invariants=missing,
        )

    @staticmethod
    def _transform(text: str, mode: RewriteMode) -> tuple[str, list[str]]:
        compact = " ".join(text.split())
        if mode is RewriteMode.COMPRESS:
            return compact.replace("非常", "").replace("事实上，", ""), [
                "压缩冗余修饰语",
                "保留命题与不可变项",
            ]
        if mode is RewriteMode.EXPAND:
            return f"{compact} 这些结果应结合研究范围与证据边界进行解释。", [
                "补充学术解释边界",
                "未增加新的事实主张",
            ]
        if mode is RewriteMode.RESTRUCTURE:
            sentences = [
                sentence.strip()
                for sentence in re.split(r"(?<=[。！？.!?])\s+", compact)
                if sentence.strip()
            ]
            return " ".join(sentences), ["按命题边界重组结构", "保持原有顺序语义"]
        return compact.replace("我们发现", "结果表明").replace("很明显", "结果显示"), [
            "调整为审慎学术语气",
            "保留事实与引用",
        ]

    @staticmethod
    def _style_score(text: str) -> float:
        informal = ("很牛", "绝对", "显然是", "随便")
        penalty = sum(term in text for term in informal)
        return max(0.0, 5.0 - penalty)


def _content_terms(text: str) -> list[str]:
    stop = {"the", "a", "an", "is", "are", "and", "of", "to", "这些", "进行", "结果"}
    return [
        term
        for term in re.findall(r"[a-z0-9%]+|[\u4e00-\u9fff]{2,}", text.casefold())
        if term not in stop
    ]
