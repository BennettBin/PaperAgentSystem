"""Evidence-bounded section and paragraph drafting."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from academic_tasks.writing_brief import WritingBrief


class ParagraphPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str
    user_points: list[str]
    statement_ids: list[str]


class DraftParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    source_statement_ids: list[str]
    evidence_ids: list[str]


class DraftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_type: str
    paragraph_plan: list[ParagraphPlan]
    paragraphs: list[DraftParagraph]
    missing_information: list[str]
    review_required: bool
    supported_fact_ratio: float


class AcademicDrafter:
    SECTION_PURPOSES = {
        "introduction": ["研究背景与问题", "研究目标与贡献"],
        "related_work": ["相关研究脉络", "差异与研究空白"],
        "methods": ["方法概述", "关键步骤与设计"],
        "experiments": ["实验设置", "数据与指标"],
        "results": ["主要结果", "结果解释与限制"],
        "discussion": ["结果含义", "局限与外推边界"],
        "conclusion": ["核心发现", "贡献与未来工作"],
    }

    def draft(self, brief: WritingBrief) -> DraftResult:
        purposes = self.SECTION_PURPOSES.get(
            brief.section_type,
            ["目标与范围", "主要内容"],
        )
        supported = [item for item in brief.evidence_map if item.allowed_as_fact]
        statements_by_id = {item.statement_id: item for item in supported}
        plans = []
        for index, purpose in enumerate(purposes):
            points = brief.user_points[index:: len(purposes)]
            statement_ids = [
                item.statement_id for item in supported[index:: len(purposes)]
            ]
            plans.append(
                ParagraphPlan(
                    purpose=purpose,
                    user_points=points,
                    statement_ids=statement_ids,
                )
            )
        paragraphs = []
        used_facts = 0
        for plan in plans:
            sentences = [f"{plan.purpose}。"]
            sentences.extend(f"本段覆盖：{point}。" for point in plan.user_points)
            evidence_ids = []
            for statement_id in plan.statement_ids:
                item = statements_by_id[statement_id]
                citations = "".join(f"[{evidence_id}]" for evidence_id in item.evidence_ids)
                sentences.append(f"{item.text} {citations}".strip())
                evidence_ids.extend(item.evidence_ids)
                used_facts += 1
            paragraphs.append(
                DraftParagraph(
                    text=" ".join(sentences),
                    source_statement_ids=plan.statement_ids,
                    evidence_ids=list(dict.fromkeys(evidence_ids)),
                )
            )
        return DraftResult(
            section_type=brief.section_type,
            paragraph_plan=plans,
            paragraphs=paragraphs,
            missing_information=brief.missing_information,
            review_required=True,
            supported_fact_ratio=used_facts / max(1, used_facts),
        )
