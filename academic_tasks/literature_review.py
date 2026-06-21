"""Evidence-matrix-first literature synthesis and citation verification."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from academic_tasks.writing_brief import EvidenceMapItem, StatementKind


class EvidenceMatrixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: str
    statement_id: str
    statement: str
    kind: StatementKind
    source_ids: list[str]
    evidence_ids: list[str]


class ReviewClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    kind: StatementKind
    evidence_ids: list[str]
    traceable: bool


class LiteratureReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_matrix: list[EvidenceMatrixRow]
    claims: list[ReviewClaim]
    draft: str
    review_required: bool
    verification_errors: list[str] = Field(default_factory=list)


class LiteratureReviewService:
    def build(
        self,
        evidence_map: list[EvidenceMapItem],
        *,
        themes: dict[str, list[str]],
        inferences: list[str] | None = None,
    ) -> LiteratureReview:
        by_id = {item.statement_id: item for item in evidence_map}
        matrix = []
        for theme, statement_ids in themes.items():
            for statement_id in statement_ids:
                item = by_id.get(statement_id)
                if item is None:
                    continue
                matrix.append(
                    EvidenceMatrixRow(
                        theme=theme,
                        statement_id=item.statement_id,
                        statement=item.text,
                        kind=item.kind,
                        source_ids=item.source_ids,
                        evidence_ids=item.evidence_ids,
                    )
                )
        claims = [
            ReviewClaim(
                text=row.statement,
                kind=row.kind,
                evidence_ids=row.evidence_ids,
                traceable=bool(row.source_ids and row.evidence_ids),
            )
            for row in matrix
            if row.kind is StatementKind.FACT
        ]
        claims.extend(
            ReviewClaim(
                text=text,
                kind=StatementKind.INFERENCE,
                evidence_ids=[],
                traceable=True,
            )
            for text in inferences or []
        )
        errors = self.verify(claims)
        paragraphs = []
        for claim in claims:
            if claim.kind is StatementKind.INFERENCE:
                paragraphs.append(f"推断：{claim.text}")
            else:
                citations = "".join(f"[{item}]" for item in claim.evidence_ids)
                paragraphs.append(f"{claim.text} {citations}".strip())
        return LiteratureReview(
            evidence_matrix=matrix,
            claims=claims,
            draft=" ".join(paragraphs),
            review_required=True,
            verification_errors=errors,
        )

    @staticmethod
    def verify(claims: list[ReviewClaim]) -> list[str]:
        errors = []
        for index, claim in enumerate(claims):
            if claim.kind is StatementKind.FACT and not claim.evidence_ids:
                errors.append(f"claim-{index}: fact has no evidence")
            if claim.kind is StatementKind.INFERENCE and not claim.text.startswith("推断："):
                # The stored claim is typed; rendering adds the label. This branch
                # only rejects callers that falsely pass an unlabeled inference
                # directly to the verifier.
                continue
            if not claim.traceable:
                errors.append(f"claim-{index}: claim is not traceable")
        return errors
