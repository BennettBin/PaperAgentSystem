"""Bounded structured 4B planning with repair, fast path and safe fallback."""

from __future__ import annotations

import json
import re
from time import monotonic
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.agent_runtime.planner import (
    CompletionPredicate,
    EvidenceRequirement,
    ExecutionPlan,
    PlanBudget,
    Planner,
    PlanStep,
    RegistrySnapshot,
    StepType,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchemaGeneratingLLM(Protocol):
    async def generate_with_schema(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str: ...


class PlannerModelMetadata(_StrictModel):
    model: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)


class PlannerContext(_StrictModel):
    requirement_brief: str = Field(min_length=1)
    difficulty: str = Field(pattern=r"^L[1-6]$")
    candidate_skills: list[str] = Field(default_factory=list, max_length=10)
    allowed_tool_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    allowed_subagents: list[str] = Field(default_factory=list)
    memory_summary: str = ""
    rag_summary: str = ""
    budget: PlanBudget = Field(default_factory=PlanBudget)


class PlannerGenerationTrace(_StrictModel):
    model: str
    profile: str
    version: str
    prompt_version: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    fast_path: bool = False
    repair_attempted: bool = False
    fallback_used: bool = False
    fallback_reason: str | None = None
    generated_step_count: int = Field(ge=1, le=8)


class PlannerOutcome(_StrictModel):
    plan: ExecutionPlan
    trace: PlannerGenerationTrace


class ConstrainedLLMPlanner:
    """Generate a V2 Plan without persisting prompts or hidden model reasoning."""

    def __init__(
        self,
        *,
        llm: SchemaGeneratingLLM,
        registry: RegistrySnapshot,
        model: PlannerModelMetadata,
        top_k_skills: int = 3,
    ) -> None:
        self._llm = llm
        self.registry = registry
        self._model = model
        self._top_k_skills = top_k_skills

    async def plan(self, context: PlannerContext) -> PlannerOutcome:
        generated_plan: ExecutionPlan | None
        if context.difficulty in {"L1", "L2"}:
            generated_plan = self._safe_workflow(context)
            return PlannerOutcome(
                plan=generated_plan,
                trace=self._trace(generated_plan, fast_path=True),
            )

        prompt = self._prompt(context)
        started = monotonic()
        input_tokens = 0
        output_tokens = 0
        repair_attempted = False
        fallback_reason: str | None = None
        generated_plan = None
        response = ""
        for attempt in range(2):
            if attempt:
                repair_attempted = True
                prompt = self._repair_prompt(response, fallback_reason or "invalid plan")
            response = await self._llm.generate_with_schema(
                prompt,
                system_prompt=(
                    "Generate only the requested Plan V2 JSON. Do not include chain of "
                    "thought or capabilities not present in the supplied registry."
                ),
                response_schema=_generation_schema(),
                max_tokens=min(context.budget.max_tokens, 4096),
                temperature=0.0,
            )
            usage = getattr(self._llm, "last_usage", None)
            input_tokens += int(getattr(usage, "input_tokens", 0))
            output_tokens += int(getattr(usage, "output_tokens", 0))
            try:
                generated_plan = self._validate_generated(response, context)
                fallback_reason = None
                break
            except Exception as exc:
                fallback_reason = f"{type(exc).__name__}: {exc}"

        fallback_used = generated_plan is None
        if generated_plan is None:
            generated_plan = self._safe_workflow(context)
        return PlannerOutcome(
            plan=generated_plan,
            trace=self._trace(
                generated_plan,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((monotonic() - started) * 1000),
                repair_attempted=repair_attempted,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            ),
        )

    def _validate_generated(
        self, response: str, context: PlannerContext
    ) -> ExecutionPlan:
        payload = _json_object(response)
        payload["global_budget"] = context.budget.model_dump(mode="python")
        plan = ExecutionPlan.model_validate(payload)
        plan.validate_against(self._effective_registry(context))
        self._validate_workflow_contract(plan, context)
        return plan

    def _safe_workflow(self, context: PlannerContext) -> ExecutionPlan:
        registry = self._effective_registry(context)
        skills = sorted(registry.skills)
        tools = sorted(registry.tools)[:2]
        if _is_missing_section_request(context.requirement_brief):
            steps = [
                PlanStep(
                    step_id="resolve-section",
                    action="Resolve the explicitly requested section",
                    step_type=StepType.SKILL if skills else StepType.GENERATE,
                    skill_name=skills[0] if skills else None,
                    completion_predicate=CompletionPredicate(
                        kind="section_resolution_attempted"
                    ),
                ),
                PlanStep(
                    step_id="detect-missing-section",
                    action="Detect that the requested section is unavailable",
                    step_type=StepType.VERIFY,
                    depends_on=["resolve-section"],
                    completion_predicate=CompletionPredicate(
                        kind="missing_section_confirmed"
                    ),
                ),
                PlanStep(
                    step_id="ask-clarification",
                    action="Ask user for clarification or a corrected section reference",
                    step_type=StepType.GENERATE,
                    depends_on=["detect-missing-section"],
                    completion_predicate=CompletionPredicate(
                        kind="clarification_requested"
                    ),
                ),
            ]
            plan = ExecutionPlan(
                goal=context.requirement_brief,
                global_budget=context.budget,
                termination_condition="the unavailable section is reported and clarification is requested",
                steps=steps,
            )
        elif context.difficulty in {"L1", "L2"} and skills:
            plan = Planner(registry).create(
                context.requirement_brief,
                skills[0],
                tools,
            )
        elif context.difficulty in {"L3", "L4", "L5", "L6"}:
            multi_paper = context.difficulty in {"L4", "L5"}
            retrieve_tool = (
                "search_document"
                if "search_document" in registry.tools
                else (tools[0] if tools else None)
            )
            verify_tool = "verify_claim" if "verify_claim" in registry.tools else None
            steps = [
                PlanStep(
                    step_id="resolve-sources",
                    action=(
                        "Resolve papers and prepare parallel paper readers"
                        if multi_paper
                        else "Resolve paper and requested section"
                    ),
                    step_type=StepType.SKILL if skills else StepType.GENERATE,
                    skill_name=skills[0] if skills else None,
                    completion_predicate=CompletionPredicate(
                        kind="sources_resolved", required_fields=["paper_ids"]
                    ),
                )
            ]
            if retrieve_tool:
                steps.append(
                    PlanStep(
                        step_id="retrieve-evidence",
                        action=(
                            "Retrieve evidence in parallel"
                            if multi_paper
                            else "Retrieve evidence for the question"
                        ),
                        step_type=StepType.TOOL_CALL,
                        tool_name=retrieve_tool,
                        depends_on=["resolve-sources"],
                        evidence_requirement=EvidenceRequirement.REQUIRED,
                        completion_predicate=CompletionPredicate(
                            kind="evidence_acquired", minimum_evidence=1
                        ),
                    )
                )
            prior = "retrieve-evidence" if retrieve_tool else "resolve-sources"
            steps.append(
                PlanStep(
                    step_id="synthesize-answer",
                    action=(
                        "Normalize evidence and compare or synthesize the answer"
                        if multi_paper
                        else "Answer with citations from retrieved evidence"
                    ),
                    step_type=StepType.GENERATE,
                    depends_on=[prior],
                    evidence_requirement=EvidenceRequirement.REQUIRED,
                    completion_predicate=CompletionPredicate(
                        kind="answer_with_evidence", minimum_evidence=1
                    ),
                )
            )
            steps.append(
                PlanStep(
                    step_id="verify-claims",
                    action="Verify claims, citations and numerical invariants",
                    step_type=StepType.TOOL_CALL if verify_tool else StepType.VERIFY,
                    tool_name=verify_tool,
                    depends_on=["synthesize-answer"],
                    completion_predicate=CompletionPredicate(kind="verification_passed"),
                )
            )
            plan = ExecutionPlan(
                goal=context.requirement_brief,
                global_budget=context.budget,
                termination_condition="the evidence-grounded answer passes verification",
                steps=steps,
            )
        else:
            plan = ExecutionPlan(
                goal=context.requirement_brief,
                global_budget=context.budget,
                termination_condition="a safe bounded answer is produced",
                steps=[
                    PlanStep(
                        step_id="generate-1",
                        action="Produce a bounded answer from supplied context",
                        completion_condition="answer is non-empty and policy compliant",
                    )
                ],
            )
        plan.global_budget = context.budget
        plan.validate_against(registry)
        return plan

    def _effective_registry(self, context: PlannerContext) -> RegistrySnapshot:
        skills = set(context.candidate_skills[: self._top_k_skills]) & self.registry.skills
        tools = set(context.allowed_tool_schemas) & self.registry.tools
        subagents = set(context.allowed_subagents) & self.registry.subagents
        return RegistrySnapshot(
            skills=skills,
            tools=tools,
            subagents=subagents,
            permitted_skills=skills,
            permitted_tools=tools,
            permitted_subagents=subagents,
        )

    def _prompt(self, context: PlannerContext) -> str:
        registry = self._effective_registry(context)
        tools = {
            name: context.allowed_tool_schemas[name]
            for name in sorted(registry.tools)
        }
        return json.dumps(
            {
                "prompt_version": self._model.prompt_version,
                "requirement_brief": context.requirement_brief,
                "difficulty": context.difficulty,
                "candidate_skills": sorted(registry.skills),
                "allowed_tools": tools,
                "allowed_subagents": sorted(registry.subagents),
                "memory_summary": context.memory_summary,
                "rag_summary": context.rag_summary,
                "budget": context.budget.model_dump(mode="json"),
                "required_workflow": _required_workflow(context),
                "constraints": {
                    "max_steps": 8,
                    "max_replans": 2,
                    "no_hidden_reasoning": True,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _validate_workflow_contract(
        plan: ExecutionPlan, context: PlannerContext
    ) -> None:
        normalized = re.sub(
            r"[_-]+",
            " ",
            " ".join(
                " ".join(
                    filter(
                        None,
                        (
                            step.step_id,
                            step.action,
                            step.skill_name,
                            step.tool_name,
                            step.subagent_name,
                            step.completion_predicate.kind
                            if step.completion_predicate
                            else None,
                        ),
                    )
                )
                for step in plan.steps
            ).casefold(),
        )
        missing = [
            stage
            for stage in _required_workflow(context)
            if not any(alias in normalized for alias in _WORKFLOW_ALIASES[stage])
        ]
        if missing:
            raise ValueError(
                "Plan is structurally valid but misses required workflow stages: "
                + ", ".join(missing)
            )

    @staticmethod
    def _repair_prompt(response: str, error: str) -> str:
        return json.dumps(
            {
                "instruction": "Repair the candidate into valid Plan V2 JSON only.",
                "public_validation_error": error[:1000],
                "candidate": response[:12_000],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _trace(
        self,
        plan: ExecutionPlan,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        fast_path: bool = False,
        repair_attempted: bool = False,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> PlannerGenerationTrace:
        return PlannerGenerationTrace(
            **self._model.model_dump(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            fast_path=fast_path,
            repair_attempted=repair_attempted,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            generated_step_count=len(plan.steps),
        )


def _json_object(value: str) -> dict[str, Any]:
    cleaned = re.sub(r"<think>.*?</think>", "", value, flags=re.I | re.S).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("Planner output must be a JSON object")
    return payload


def _generation_schema() -> dict[str, Any]:
    """Tighten the read-compatible V2 schema for newly generated plans."""

    schema = ExecutionPlan.model_json_schema()
    step_schema = schema.get("$defs", {}).get("PlanStep", {})
    properties = step_schema.get("properties", {})
    if "completion_predicate" in properties:
        properties["completion_predicate"] = {
            "$ref": "#/$defs/CompletionPredicate"
        }
    required = list(step_schema.get("required", []))
    if "completion_predicate" not in required:
        required.append("completion_predicate")
    step_schema["required"] = required
    return schema


_WORKFLOW_ALIASES: dict[str, tuple[str, ...]] = {
    "resolve_sources": ("resolve source", "resolve paper", "parse document", "paper reader"),
    "resolve_section": ("resolve section", "requested section", "get document section"),
    "detect_missing_section": ("missing section", "section unavailable", "absent section"),
    "ask_clarification": ("ask user", "clarif", "corrected section"),
    "retrieve_evidence": ("retrieve evidence", "search document", "evidence acquired"),
    "parallel_retrieve": ("parallel retrieve", "retrieve evidence in parallel", "paper reader agent"),
    "answer_with_citations": ("answer with citation", "answer with evidence"),
    "normalize_evidence": ("normalize evidence", "evidence matrix"),
    "compare_or_synthesize": ("compare", "synthesi", "comparison"),
    "verify_claims": ("verify claim", "verification passed", "claim verifier"),
}


def _is_missing_section_request(requirement: str) -> bool:
    normalized = requirement.casefold()
    missing_marker = any(word in normalized for word in ("absent", "missing", "unavailable"))
    section_marker = any(word in normalized for word in ("section", "appendix"))
    return missing_marker and section_marker


def _required_workflow(context: PlannerContext) -> list[str]:
    if _is_missing_section_request(context.requirement_brief):
        return ["resolve_section", "detect_missing_section", "ask_clarification"]
    if context.difficulty in {"L4", "L5"}:
        return [
            "resolve_sources",
            "parallel_retrieve",
            "normalize_evidence",
            "compare_or_synthesize",
            "verify_claims",
        ]
    return ["resolve_sources", "retrieve_evidence", "answer_with_citations"]
