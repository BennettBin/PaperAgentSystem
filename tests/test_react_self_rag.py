import json

import pytest

from agent_runtime.react_self_rag import ReActSelfRAGController


class DecisionLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_model_decides_to_retrieve_a_named_section() -> None:
    llm = DecisionLLM(
        {
            "action": "retrieve",
            "search_query": "ablation experiments",
            "section_hint": "Experiments",
            "clarification_question": None,
        }
    )
    controller = ReActSelfRAGController(llm)

    decision = await controller.decide(
        "请只分析 Experiments 章节中的消融实验",
        has_files=True,
    )

    assert decision.action == "retrieve"
    assert decision.search_query == "ablation experiments"
    assert decision.section_hint == "Experiments"
    assert llm.prompts


@pytest.mark.asyncio
async def test_model_can_ask_one_question_and_preserve_original_request() -> None:
    llm = DecisionLLM(
        {
            "action": "clarify",
            "search_query": None,
            "section_hint": None,
            "clarification_question": "你希望分析哪一篇论文或哪个章节？",
        }
    )
    controller = ReActSelfRAGController(llm)

    decision = await controller.decide("帮我深入分析一下", has_files=False)

    assert decision.action == "clarify"
    assert decision.clarification_question
    assert decision.original_request == "帮我深入分析一下"


@pytest.mark.asyncio
async def test_general_question_can_skip_rag() -> None:
    llm = DecisionLLM(
        {
            "action": "answer",
            "search_query": None,
            "section_hint": None,
            "clarification_question": None,
        }
    )
    decision = await ReActSelfRAGController(llm).decide(
        "你好，请介绍一下你能做什么",
        has_files=True,
    )

    assert decision.action == "answer"


@pytest.mark.asyncio
async def test_section_hint_is_inferred_when_model_omits_it() -> None:
    llm = DecisionLLM(
        {
            "action": "retrieve",
            "search_query": "消融实验",
            "section_hint": None,
            "clarification_question": None,
        }
    )

    decision = await ReActSelfRAGController(llm).decide(
        "只看实验章节的消融实验",
        has_files=True,
    )

    assert decision.section_hint == "Experiments"
