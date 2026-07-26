"""Workspace-filtered hybrid retrieval with RRF and reranking."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.ports.llm_client import EmbeddingClient, RerankerClient
from backend.infrastructure.postgres.models import DocumentChunkModel, DocumentSectionModel
from backend.rag.local_models import retrieval_terms
from backend.rag.section_resolver import (
    SectionRecord,
    SectionReferenceParser,
    SectionResolution,
    SectionResolver,
)


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


@dataclass(frozen=True, slots=True)
class SectionSearchResult:
    resolution: SectionResolution
    mode: Literal["qa", "summary"]
    scope_section_ids: tuple[str, ...]
    hits: tuple[RetrievalHit, ...]
    truncated: bool = False


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


class ExactMatchRetriever:
    """Keyword and regex-style exact recall over normalized chunk text."""

    def retrieve(
        self, query: str, models: list[DocumentChunkModel], limit: int
    ) -> list[DocumentChunkModel]:
        phrases = [term for term in _terms(query) if len(term) > 1]
        if not phrases:
            return []
        pattern = re.compile("|".join(re.escape(term) for term in phrases), re.I)
        return sorted(
            (model for model in models if pattern.search(model.searchable_text)),
            key=lambda model: (-_exact_score(pattern, model.searchable_text), model.id),
        )[:limit]


class SectionRetriever:
    """Restrict candidates to matching section metadata when a section is named."""

    def scope(
        self, models: list[DocumentChunkModel], section_hint: str | None
    ) -> list[DocumentChunkModel]:
        section_models = _section_matches(models, section_hint)
        return section_models or models


class VectorRetriever:
    def retrieve(
        self,
        query_vector: list[float],
        models: list[DocumentChunkModel],
        limit: int,
    ) -> list[DocumentChunkModel]:
        scored = [
            (_cosine(query_vector, list(model.embedding)), model) for model in models
        ]
        return [
            model
            for score, model in sorted(scored, key=lambda item: (-item[0], item[1].id))
            if score > 0
        ][:limit]


class BM25Retriever:
    """Small dependency-free BM25 implementation for lexical recall."""

    def retrieve(
        self, query: str, models: list[DocumentChunkModel], limit: int
    ) -> list[DocumentChunkModel]:
        query_terms = _terms(query)
        if not query_terms:
            return []
        corpus_terms = [_terms(model.searchable_text) for model in models]
        document_count = max(1, len(corpus_terms))
        document_frequencies = {
            term: sum(1 for terms in corpus_terms if term in set(terms))
            for term in set(query_terms)
        }
        average_length = sum(len(terms) for terms in corpus_terms) / document_count
        scored = [
            (
                _bm25_score(
                    query_terms,
                    corpus_terms[index],
                    document_frequencies,
                    document_count,
                    average_length,
                ),
                model,
            )
            for index, model in enumerate(models)
        ]
        return [
            model
            for score, model in sorted(scored, key=lambda item: (-item[0], item[1].id))
            if score > 0
        ][:limit]


class ResultMerger:
    def __init__(self, rrf_k: int) -> None:
        self._rrf_k = rrf_k

    def merge(self, rankings: list[list[DocumentChunkModel]]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for ranking in rankings:
            for rank, model in enumerate(ranking, start=1):
                scores[model.id] = scores.get(model.id, 0.0) + 1 / (self._rrf_k + rank)
        return scores


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
        self._exact = ExactMatchRetriever()
        self._sections = SectionRetriever()
        self._vectors = VectorRetriever()
        self._bm25 = BM25Retriever()
        self._merger = ResultMerger(rrf_k)
        self._section_parser = SectionReferenceParser()
        self._section_resolver = SectionResolver()

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
        embedding_fingerprint = _embedding_fingerprint(self._embeddings)
        with self._sessions() as session:
            models = self._load_filtered(session, workspace_id, file_ids)
            models = self._sections.scope(models, section_hint)
        return await self._rank_models(
            query,
            query_text,
            query_vector,
            models,
            limit=limit,
            expand_section=expand_section,
            embedding_fingerprint=embedding_fingerprint,
        )

    async def search_section(
        self,
        query: str,
        *,
        workspace_id: str,
        file_ids: set[str] | None = None,
        limit: int | None = None,
        max_context_characters: int = 12_000,
    ) -> SectionSearchResult:
        """Resolve an explicit section reference before retrieving its evidence.

        Resolution happens against a workspace/file-scoped catalog. A resolved parent
        section includes all descendants in the same document. Summary mode preserves
        document order and uses deterministic head/middle/tail coverage when the
        complete section exceeds the context budget.
        """

        reference = self._section_parser.parse(query)
        with self._sessions() as session:
            section_models = self._load_sections(session, workspace_id, file_ids)
            records = [_section_record(model) for model in section_models]
            resolution = self._section_resolver.resolve(reference, records)
            if resolution.status != "resolved" or resolution.selected is None:
                return SectionSearchResult(
                    resolution=resolution,
                    mode=reference.requested_mode,
                    scope_section_ids=(),
                    hits=(),
                )
            scope_models = _section_scope(section_models, resolution.selected)
            scope_ids = tuple(model.section_id for model in scope_models)
            chunks = self._load_filtered(
                session,
                workspace_id,
                {resolution.selected.file_id},
                section_ids=set(scope_ids),
            )

        if reference.requested_mode == "summary":
            by_section = {model.section_id: model.ordinal for model in scope_models}
            ordered = sorted(
                chunks,
                key=lambda model: (
                    by_section.get(model.section_id or "", 10**9),
                    model.chunk_index_in_section or 0,
                    model.page_start,
                    model.id,
                ),
            )
            selected, truncated = _summary_coverage(
                ordered,
                max_context_characters=max_context_characters,
            )
            summary_hits = tuple(
                _hit(model, max(0.0, 1.0 - index * 0.001))
                for index, model in enumerate(selected)
            )
            return SectionSearchResult(
                resolution=resolution,
                mode="summary",
                scope_section_ids=scope_ids,
                hits=summary_hits,
                truncated=truncated,
            )

        rewrites = await self._rewriter.rewrite(query)
        query_text = " ".join(rewrites).strip()
        query_vector = _pad(await self._embeddings.embed(query_text))
        embedding_fingerprint = _embedding_fingerprint(self._embeddings)
        qa_hits = await self._rank_models(
            query,
            query_text,
            query_vector,
            chunks,
            limit=limit,
            expand_section=False,
            embedding_fingerprint=embedding_fingerprint,
        )
        qa_hits = _expand_adjacent_context(
            chunks,
            qa_hits,
            limit=limit or self._final_limit,
            section_ordinals={
                model.section_id: model.ordinal for model in scope_models
            },
        )
        return SectionSearchResult(
            resolution=resolution,
            mode="qa",
            scope_section_ids=scope_ids,
            hits=tuple(qa_hits),
        )

    async def _rank_models(
        self,
        query: str,
        query_text: str,
        query_vector: list[float],
        models: list[DocumentChunkModel],
        *,
        limit: int | None,
        expand_section: bool,
        embedding_fingerprint: str | None,
    ) -> list[RetrievalHit]:
        exact_rank = self._exact.retrieve(query_text, models, self._candidate_limit)
        vector_models = (
            models
            if embedding_fingerprint is None
            else [
                model
                for model in models
                if model.embedding_status == "ready"
                and model.embedding_fingerprint == embedding_fingerprint
            ]
        )
        vector_rank = self._vectors.retrieve(
            query_vector, vector_models, self._candidate_limit
        )
        bm25_rank = self._bm25.retrieve(query_text, models, self._candidate_limit)
        scores = self._merger.merge([exact_rank, vector_rank, bm25_rank])
        by_id = {model.id: model for model in models}
        fused = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        if not fused:
            return []
        documents = [
            f"{' / '.join(by_id[chunk_id].section_path)}\n{by_id[chunk_id].text}"
            for chunk_id in fused
        ]
        reranked = await self._reranker.rerank(
            query,
            documents,
            top_k=min(self._final_limit, len(documents)),
        )
        selected = sorted(
            reranked[: (limit or self._final_limit)],
            key=lambda item: (-(scores[fused[item[0]]] + item[1]), item[0]),
        )
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
        *,
        section_ids: set[str] | None = None,
    ) -> list[DocumentChunkModel]:
        statement = select(DocumentChunkModel).where(
            DocumentChunkModel.workspace_id == workspace_id,
            DocumentChunkModel.level == "child",
        )
        if file_ids is not None:
            if not file_ids:
                return []
            statement = statement.where(DocumentChunkModel.file_id.in_(file_ids))
        if section_ids is not None:
            if not section_ids:
                return []
            statement = statement.where(DocumentChunkModel.section_id.in_(section_ids))
        return list(session.scalars(statement))

    @staticmethod
    def _load_sections(
        session: Session,
        workspace_id: str,
        file_ids: set[str] | None,
    ) -> list[DocumentSectionModel]:
        statement = select(DocumentSectionModel).where(
            DocumentSectionModel.workspace_id == workspace_id
        )
        if file_ids is not None:
            if not file_ids:
                return []
            statement = statement.where(DocumentSectionModel.file_id.in_(file_ids))
        statement = statement.order_by(
            DocumentSectionModel.document_id,
            DocumentSectionModel.ordinal,
            DocumentSectionModel.section_id,
        )
        return list(session.scalars(statement))


def _terms(value: str) -> list[str]:
    return retrieval_terms(value)


def _exact_score(pattern: re.Pattern[str], text_value: str) -> int:
    return len(pattern.findall(text_value))


def _bm25_score(
    query_terms: list[str],
    document_terms: list[str],
    document_frequencies: dict[str, int],
    document_count: int,
    average_length: float,
) -> float:
    k1 = 1.5
    b = 0.75
    length = max(1, len(document_terms))
    term_counts = {term: document_terms.count(term) for term in set(query_terms)}
    score = 0.0
    for term in query_terms:
        frequency = term_counts.get(term, 0)
        if frequency == 0:
            continue
        idf = math.log(
            1
            + (document_count - document_frequencies.get(term, 0) + 0.5)
            / (document_frequencies.get(term, 0) + 0.5)
        )
        denominator = frequency + k1 * (1 - b + b * length / max(1.0, average_length))
        score += idf * (frequency * (k1 + 1)) / denominator
    return score


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


def _embedding_fingerprint(embeddings: EmbeddingClient) -> str | None:
    profile = getattr(embeddings, "profile", None)
    return profile.fingerprint if profile is not None else None


def _section_record(model: DocumentSectionModel) -> SectionRecord:
    return SectionRecord(
        section_id=model.section_id,
        document_id=model.document_id,
        file_id=model.file_id,
        number=model.number,
        title=model.title,
        normalized_title=model.normalized_title,
        section_path=list(model.section_path or []),
        parent_section_id=model.parent_section_id,
        ordinal=model.ordinal,
    )


def _section_scope(
    models: list[DocumentSectionModel],
    selected: SectionRecord,
) -> list[DocumentSectionModel]:
    same_document = [
        model
        for model in models
        if model.document_id == selected.document_id
        and model.file_id == selected.file_id
    ]
    included = {selected.section_id}
    changed = True
    while changed:
        changed = False
        for model in same_document:
            if (
                model.section_id not in included
                and model.parent_section_id in included
            ):
                included.add(model.section_id)
                changed = True
    return sorted(
        (model for model in same_document if model.section_id in included),
        key=lambda model: (model.ordinal, model.section_id),
    )


def _summary_coverage(
    models: list[DocumentChunkModel],
    *,
    max_context_characters: int,
) -> tuple[list[DocumentChunkModel], bool]:
    if not models:
        return [], False
    if max_context_characters < 1:
        raise ValueError("max_context_characters must be positive")
    if sum(len(model.text) for model in models) <= max_context_characters:
        return models, False

    # Preserve structural coverage before filling remaining budget. This is a
    # deterministic context-selection fallback; model summarization happens later.
    essential = {0, len(models) // 2, len(models) - 1}
    seen_sections: set[str | None] = set()
    for index, model in enumerate(models):
        if model.section_id not in seen_sections:
            essential.add(index)
            seen_sections.add(model.section_id)
    selected = set(essential)
    used = sum(len(models[index].text) for index in essential)
    for index, model in enumerate(models):
        if index in selected:
            continue
        size = len(model.text)
        if used + size <= max_context_characters:
            selected.add(index)
            used += size
    return [models[index] for index in sorted(selected)], True


def _expand_adjacent_context(
    models: list[DocumentChunkModel],
    ranked_hits: list[RetrievalHit],
    *,
    limit: int,
    section_ordinals: dict[str, int] | None = None,
) -> list[RetrievalHit]:
    if not ranked_hits or limit < 1:
        return []
    ordered = sorted(
        models,
        key=lambda model: (
            model.file_id,
            (section_ordinals or {}).get(model.section_id or "", 10**9),
            model.chunk_index_in_section or 0,
            model.page_start,
            model.id,
        ),
    )
    positions = {model.id: index for index, model in enumerate(ordered)}
    selected_positions: set[int] = set()
    for hit in ranked_hits:
        position = positions.get(hit.chunk_id)
        if position is None:
            continue
        for candidate in (position - 1, position, position + 1):
            if 0 <= candidate < len(ordered):
                selected_positions.add(candidate)
        if len(selected_positions) >= limit:
            break
    selected = sorted(selected_positions)[:limit]
    score_by_id = {hit.chunk_id: hit.score for hit in ranked_hits}
    primary_score = ranked_hits[0].score
    return [
        _hit(
            ordered[position],
            score_by_id.get(ordered[position].id, max(0.0, primary_score - 0.01)),
        )
        for position in selected
    ]


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
