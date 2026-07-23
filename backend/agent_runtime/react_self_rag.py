"""Bounded ReAct controller for clarification and Self-RAG routing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from backend.core.ports.llm_client import LLMClient


class ReActDecisionPayload(BaseModel):
    action: Literal["clarify", "retrieve", "answer"]
    search_query: str | None = None
    section_hint: str | None = None
    clarification_question: str | None = None


@dataclass(frozen=True, slots=True)
class ReActDecision:
    action: Literal["clarify", "retrieve", "answer"]
    original_request: str
    search_query: str | None = None
    section_hint: str | None = None
    clarification_question: str | None = None


class ReActSelfRAGController:
    """One bounded thought/action decision; hidden reasoning is never persisted."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def decide(
        self,
        request: str,
        *,
        has_files: bool,
        clarification_answer: str | None = None,
        conversation_context: str = "",
    ) -> ReActDecision:
        prompt = (
            "为论文助手选择下一步动作。只输出 JSON，不输出推理过程。\n"
            "动作规则：\n"
            "- clarify：目标、论文或章节不明确，且无法安全继续；只问一个关键问题。\n"
            "- retrieve：回答需要论文正文事实、数字、章节内容或引用。\n"
            "- answer：寒暄、能力说明或不依赖论文正文的一般问题。\n"
            f"当前是否有关联论文：{has_files}\n"
            f"相关历史问答：{conversation_context or '无'}\n"
            f"原始需求：{request}\n"
            f"用户补充：{clarification_answer or '无'}"
        )
        schema = ReActDecisionPayload.model_json_schema()
        try:
            raw = await self._llm.generate_with_schema(
                prompt,
                response_schema=schema,
                max_tokens=256,
                temperature=0,
            )
            payload = ReActDecisionPayload.model_validate(json.loads(raw))
        except Exception:
            payload = self._fallback(request, has_files)
        if payload.action == "retrieve" and not payload.search_query:
            payload.search_query = request
        if payload.action == "retrieve" and not payload.section_hint:
            payload.section_hint = _infer_section_hint(request)
        if payload.action == "clarify" and not payload.clarification_question:
            payload.clarification_question = "请补充要处理的论文、章节或具体目标。"
        return ReActDecision(
            action=payload.action,
            original_request=request,
            search_query=payload.search_query,
            section_hint=payload.section_hint,
            clarification_question=payload.clarification_question,
        )

    @staticmethod
    def _fallback(request: str, has_files: bool) -> ReActDecisionPayload:
        paper_terms = (
            "论文",
            "章节",
            "方法",
            "实验",
            "结果",
            "引用",
            "摘要",
            "section",
            "paper",
            "method",
            "result",
        )
        if any(term in request.casefold() for term in paper_terms):
            if has_files:
                return ReActDecisionPayload(action="retrieve", search_query=request)
            return ReActDecisionPayload(
                action="clarify",
                clarification_question="请上传或选择要分析的论文。",
            )
        if len(request.strip()) < 8 and not has_files:
            return ReActDecisionPayload(
                action="clarify",
                clarification_question="你希望我具体完成什么任务？",
            )
        return ReActDecisionPayload(action="answer")


def _infer_section_hint(request: str) -> str | None:
    aliases = {
        "摘要": "Abstract",
        "引言": "Introduction",
        "相关工作": "Related Work",
        "方法": "Methods",
        "实验": "Experiments",
        "结果": "Results",
        "讨论": "Discussion",
        "结论": "Conclusion",
        "abstract": "Abstract",
        "introduction": "Introduction",
        "method": "Methods",
        "experiment": "Experiments",
        "result": "Results",
        "discussion": "Discussion",
        "conclusion": "Conclusion",
    }
    lower = request.casefold()
    for marker, section in aliases.items():
        if marker in lower:
            return section
    return None
