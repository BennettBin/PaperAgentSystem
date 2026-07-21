"""Workspace-filtered hybrid retrieval with RRF and reranking."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from core.ports.llm_client import EmbeddingClient, RerankerClient
from infrastructure.postgres.models import DocumentChunkModel
from rag.local_models import retrieval_terms


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: str
    workspace_id: str
    file_id: str
    text: str
    section_path: tuple[str, ...]
    page_start: int
    page_end: int
    bbox: tuple[float, float, float, float]
    source_block_ids: tuple[str, ...]
    score: float


class QueryRewriter(Protocol):
    async def rewrite(self, query: str) -> list[str]: ...


class RuleQueryRewriter:
    SYNONYMS = {
        "方法": "method methodology",
        "结果": "result results finding",
        "局限": "limitation limitation",
        "数据集": "dataset data",
    }

    async def rewrite(self, query: str) -> list[str]:
        expanded = query
        for source, target in self.SYNONYMS.items():
            if source in query:
                expanded = f"{expanded} {target}"
        return list(dict.fromkeys([query.strip(), expanded.strip()]))


class HybridRetriever:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embeddings: EmbeddingClient,
        reranker: RerankerClient,
        *,
        rewriter: QueryRewriter | None = None,
        candidate_limit: int = 30,
        final_limit: int = 8,
        rrf_k: int = 60,
    ) -> None:
        self._sessions = session_factory
        self._embeddings = embeddings
        self._reranker = reranker
        self._rewriter = rewriter or RuleQueryRewriter()
        self._candidate_limit = candidate_limit
        self._final_limit = final_limit
        self._rrf_k = rrf_k

    async def search(
        self,
        query: str,
        *,
        workspace_id: str,
        file_ids: set[str] | None = None,
        limit: int | None = None,
        section_hint: str | None = None,
        expand_section: bool = False,
    ) -> list[RetrievalHit]:
        rewrites = await self._rewriter.rewrite(query)
        query_text = " ".join([*rewrites, section_hint or ""]).strip()
        query_vector = _pad(await self._embeddings.embed(query_text))
        with self._sessions() as session:
            models = self._load_filtered(session, workspace_id, file_ids)
            section_models = _section_matches(models, section_hint)
            if section_models:
                models = section_models
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                vector_ids = self._postgres_vector_rank(
                    session, workspace_id, file_ids, query_vector
                )
                keyword_ids = self._postgres_keyword_rank(
                    session, workspace_id, file_ids, query_text
                )
                by_id = {model.id: model for model in models}
                vector_rank = [by_id[item] for item in vector_ids if item in by_id]
                keyword_rank = [by_id[item] for item in keyword_ids if item in by_id]
            else:
                vector_rank = sorted(
                    models,
                    key=lambda model: -_cosine(query_vector, list(model.embedding)),
                )[: self._candidate_limit]
                terms = set(_terms(query_text))
                keyword_rank = sorted(
                    models,
                    key=lambda model: (
                        -_keyword_score(terms, model.searchable_text),
                        model.id,
                    ),
                )[: self._candidate_limit]
        scores: dict[str, float] = {}
        by_id = {model.id: model for model in models}
        for ranking in (vector_rank, keyword_rank):
            for rank, model in enumerate(ranking, start=1):
                scores[model.id] = scores.get(model.id, 0.0) + 1 / (self._rrf_k + rank)
        fused = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        documents = [
            f"{' / '.join(by_id[chunk_id].section_path)}\n{by_id[chunk_id].text}"
            for chunk_id in fused
        ]
        reranked = await self._reranker.rerank(
            query,
            documents,
            top_k=min(self._final_limit, len(documents)),
        )
        selected = reranked[: (limit or self._final_limit)]
        hits = [
            _hit(by_id[fused[index]], scores[fused[index]] + rerank_score)
            for index, rerank_score in selected
        ]
        if expand_section and hits:
            hits = _expand_section(models, hits, limit or self._final_limit)
        return hits

    @staticmethod
    def _load_filtered(
        session: Session,
        workspace_id: str,
        file_ids: set[str] | None,
    ) -> list[DocumentChunkModel]:
        statement = select(DocumentChunkModel).where(
            DocumentChunkModel.workspace_id == workspace_id,
            DocumentChunkModel.level == "child",
        )
        if file_ids is not None:
            if not file_ids:
                return []
            statement = statement.where(DocumentChunkModel.file_id.in_(file_ids))
        return list(session.scalars(statement))

    def _postgres_vector_rank(
        self,
        session: Session,
        workspace_id: str,
        file_ids: set[str] | None,
        vector: list[float],
    ) -> list[str]:
        file_clause = ""
        parameters: dict[str, object] = {
            "workspace_id": workspace_id,
            "embedding": "[" + ",".join(str(value) for value in vector) + "]",
            "limit": self._candidate_limit,
        }
        if file_ids is not None:
            file_clause = "AND file_id = ANY(:file_ids)"
            parameters["file_ids"] = list(file_ids)
        rows = session.execute(
            text(
                "SELECT id FROM document_chunks "
                "WHERE workspace_id = :workspace_id AND level = 'child' "
                f"{file_clause} "
                "ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit"
            ),
            parameters,
        )
        return [str(row.id) for row in rows]

    def _postgres_keyword_rank(
        self,
        session: Session,
        workspace_id: str,
        file_ids: set[str] | None,
        query: str,
    ) -> list[str]:
        file_clause = ""
        parameters: dict[str, object] = {
            "workspace_id": workspace_id,
            "query": query,
            "limit": self._candidate_limit,
        }
        if file_ids is not None:
            file_clause = "AND file_id = ANY(:file_ids)"
            parameters["file_ids"] = list(file_ids)
        rows = session.execute(
            text(
                "SELECT id FROM document_chunks "
                "WHERE workspace_id = :workspace_id AND level = 'child' "
                f"{file_clause} "
                "ORDER BY ts_rank_cd("
                "to_tsvector('simple', searchable_text), "
                "plainto_tsquery('simple', :query)"
                ") DESC LIMIT :limit"
            ),
            parameters,
        )
        return [str(row.id) for row in rows]


def _terms(value: str) -> list[str]:
    return retrieval_terms(value)


def _keyword_score(query_terms: set[str], text_value: str) -> float:
    document_terms = set(_terms(text_value))
    return len(query_terms & document_terms) / max(1, len(query_terms))


def _cosine(left: list[float], right: list[float]) -> float:
    size = max(len(left), len(right))
    if not size:
        return 0
    a = left + [0.0] * (size - len(left))
    b = right + [0.0] * (size - len(right))
    denominator = math.sqrt(sum(value * value for value in a)) * math.sqrt(
        sum(value * value for value in b)
    )
    return 0 if denominator == 0 else sum(x * y for x, y in zip(a, b)) / denominator


def _pad(vector: list[float], dimension: int = 1024) -> list[float]:
    return (vector + [0.0] * dimension)[:dimension]


def _hit(model: DocumentChunkModel, score: float) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=model.id,
        workspace_id=model.workspace_id,
        file_id=model.file_id,
        text=model.text,
        section_path=tuple(model.section_path),
        page_start=model.page_start,
        page_end=model.page_end,
        bbox=(
            model.bbox_json[0],
            model.bbox_json[1],
            model.bbox_json[2],
            model.bbox_json[3],
        ),
        source_block_ids=tuple(model.source_block_ids),
        score=score,
    )


def _section_matches(
    models: list[DocumentChunkModel], section_hint: str | None
) -> list[DocumentChunkModel]:
    if not section_hint:
        return []
    aliases = {
        "实验": "experiments experiment",
        "方法": "methods methodology method",
        "结果": "results result findings",
        "引言": "introduction",
        "结论": "conclusion conclusions",
        "讨论": "discussion",
        "摘要": "abstract",
    }
    expanded_hint = f"{section_hint} {aliases.get(section_hint.casefold(), '')}"
    hint_terms = set(_terms(expanded_hint))
    if not hint_terms:
        return []
    return [
        model
        for model in models
        if hint_terms & set(_terms(" ".join(model.section_path)))
    ]


def _expand_section(
    models: list[DocumentChunkModel],
    ranked_hits: list[RetrievalHit],
    limit: int,
) -> list[RetrievalHit]:
    primary = ranked_hits[0]
    same_section = sorted(
        (
            model
            for model in models
            if model.file_id == primary.file_id
            and tuple(model.section_path) == primary.section_path
        ),
        key=lambda model: (model.page_start, model.created_at, model.id),
    )
    score_by_id = {hit.chunk_id: hit.score for hit in ranked_hits}
    expanded = [
        _hit(model, score_by_id.get(model.id, max(0.0, primary.score - 0.01)))
        for model in same_section
    ]
    seen = {hit.chunk_id for hit in expanded}
    expanded.extend(hit for hit in ranked_hits if hit.chunk_id not in seen)
    return expanded[:limit]
