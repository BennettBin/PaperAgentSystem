from __future__ import annotations

import httpx
import pytest

from backend.apps.api.product_service import (
    _is_scholarly_discovery_request,
    _merge_scholarly_results,
    _render_scholarly_results,
    _scholarly_search_query,
)
from backend.core.errors import ErrorCode, ProjectError
from backend.infrastructure.scholarly.providers import (
    ArxivSearchProvider,
    CrossrefSearchProvider,
    OpenAlexSearchProvider,
    SemanticScholarSearchProvider,
)
from backend.tool_runtime.runtime import ToolContext
from backend.tool_runtime.scholarly_search_tools import (
    CrossrefSearchTool,
    ScholarlySearchInput,
)


def _client(payload: str, content_type: str = "application/json") -> httpx.AsyncClient:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=payload, headers={"content-type": content_type})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_crossref_normalizes_work_metadata() -> None:
    client = _client(
        '{"message":{"total-results":1,"items":[{"DOI":"10.1000/demo",'
        '"title":["A Demo Paper"],"author":[{"given":"Ada","family":"Lovelace"}],'
        '"published":{"date-parts":[[2024,1,1]]},"container-title":["DemoConf"],'
        '"URL":"https://doi.org/10.1000/demo","is-referenced-by-count":12}]}}'
    )
    async with client:
        page = await CrossrefSearchProvider(client).search("demo", limit=5)

    assert page.source == "crossref"
    assert page.total == 1
    assert page.works[0].doi == "10.1000/demo"
    assert page.works[0].authors == ("Ada Lovelace",)
    assert page.works[0].citation_count == 12


@pytest.mark.asyncio
async def test_semantic_scholar_normalizes_work_metadata() -> None:
    client = _client(
        '{"total":1,"data":[{"paperId":"s2-1","title":"Semantic Paper",'
        '"abstract":"Useful abstract","year":2023,"venue":"ACL",'
        '"authors":[{"name":"Grace Hopper"}],"citationCount":7,'
        '"externalIds":{"DOI":"10.2000/semantic"},"url":"https://s2/paper"}]}'
    )
    async with client:
        page = await SemanticScholarSearchProvider(client).search("semantic", limit=5)

    assert page.source == "semantic_scholar"
    assert page.works[0].external_id == "s2-1"
    assert page.works[0].abstract == "Useful abstract"
    assert page.works[0].doi == "10.2000/semantic"


@pytest.mark.asyncio
async def test_openalex_rebuilds_abstract_and_normalizes_metadata() -> None:
    client = _client(
        '{"meta":{"count":1},"results":[{"id":"https://openalex.org/W1",'
        '"display_name":"Open Paper","publication_year":2022,'
        '"authorships":[{"author":{"display_name":"Alan Turing"}}],'
        '"primary_location":{"source":{"display_name":"Nature"},'
        '"landing_page_url":"https://example/paper"},"doi":"https://doi.org/10.3000/open",'
        '"cited_by_count":4,"abstract_inverted_index":{"Hello":[0],"world":[1]}}]}'
    )
    async with client:
        page = await OpenAlexSearchProvider(client).search("open", limit=5)

    assert page.source == "openalex"
    assert page.works[0].abstract == "Hello world"
    assert page.works[0].doi == "10.3000/open"
    assert page.works[0].venue == "Nature"


@pytest.mark.asyncio
async def test_arxiv_parses_atom_feed() -> None:
    client = _client(
        """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
          <opensearch:totalResults>1</opensearch:totalResults>
          <entry><id>http://arxiv.org/abs/2401.00001v1</id><updated>2024-01-02T00:00:00Z</updated>
          <published>2024-01-01T00:00:00Z</published><title> Arxiv Paper </title>
          <summary> An abstract. </summary><author><name>Edsger Dijkstra</name></author>
          <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate" type="text/html" />
          </entry></feed>""",
        "application/atom+xml",
    )
    async with client:
        page = await ArxivSearchProvider(client).search("arxiv", limit=5)

    assert page.source == "arxiv"
    assert page.works[0].external_id == "2401.00001v1"
    assert page.works[0].year == 2024
    assert page.works[0].authors == ("Edsger Dijkstra",)


@pytest.mark.asyncio
async def test_provider_maps_rate_limit_to_project_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "slow down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProjectError) as captured:
            await CrossrefSearchProvider(client).search("demo", limit=5)

    assert captured.value.code == ErrorCode.RESOURCE_EXHAUSTED
    assert captured.value.is_retryable is True


@pytest.mark.asyncio
async def test_tool_uses_validated_input_and_system_context() -> None:
    client = _client('{"message":{"total-results":0,"items":[]}}')
    context = ToolContext(
        workspace_id="workspace",
        user_id="user",
        conversation_id="conversation",
        task_id="task",
        trace_id="trace",
        permissions=frozenset({"external:read"}),
        allowed_tools=frozenset({"search_crossref"}),
    )
    async with client:
        output = await CrossrefSearchTool(CrossrefSearchProvider(client)).execute(
            context,
            ScholarlySearchInput(query="agent systems", limit=5),
        )

    assert output.source == "crossref"
    assert output.query == "agent systems"
    assert output.works == []


def test_discovery_intent_does_not_capture_uploaded_pdf_retrieval() -> None:
    assert _is_scholarly_discovery_request("帮我找几篇关于 Agent RAG 的论文") is True
    assert _is_scholarly_discovery_request("find papers about agentic RAG") is True
    assert _is_scholarly_discovery_request("检索这篇论文中的实验结果") is False
    assert _scholarly_search_query("帮我找几篇关于 Agentic RAG 的论文") == "Agentic RAG"


def test_merge_prefers_doi_and_preserves_all_sources() -> None:
    outputs = [
        {
            "source": "crossref",
            "works": [
                {
                    "source": "crossref",
                    "external_id": "10.1000/demo",
                    "title": "A Demo Paper",
                    "doi": "10.1000/demo",
                    "authors": ["Ada"],
                    "citation_count": 3,
                }
            ],
        },
        {
            "source": "semantic_scholar",
            "works": [
                {
                    "source": "semantic_scholar",
                    "external_id": "s2",
                    "title": "A Demo Paper",
                    "doi": "10.1000/demo",
                    "url": "https://example/paper",
                    "authors": [],
                    "citation_count": 8,
                }
            ],
        },
    ]

    works = _merge_scholarly_results(outputs)

    assert len(works) == 1
    assert works[0]["sources"] == ["crossref", "semantic_scholar"]
    assert works[0]["citation_count"] == 8
    assert works[0]["url"] == "https://example/paper"
    rendered = _render_scholarly_results("demo", works, {})
    assert "## 论文检索结果" in rendered
    assert "不是已核验的论文正文证据" in rendered
