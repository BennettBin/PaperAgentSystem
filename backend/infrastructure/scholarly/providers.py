"""Bounded async HTTP adapters for public scholarly metadata APIs."""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

import httpx

from backend.core.errors import ErrorCategory, ErrorCode, ProjectError
from backend.core.ports.scholarly import ScholarlySearchPage, ScholarlyWork

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"


class _HttpScholarlyProvider:
    source: str

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = {"User-Agent": "PaperAgentSystem/0.1 scholarly-search"}
        request_headers.update(headers or {})
        try:
            if self._client is not None:
                response = await self._client.get(
                    url,
                    params=params,
                    headers=request_headers,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.get(
                        url,
                        params=params,
                        headers=request_headers,
                    )
        except httpx.TimeoutException as exc:
            raise ProjectError(
                ErrorCode.DEADLINE_EXCEEDED,
                f"{self.source} request timed out",
                {"source": self.source},
                cause=exc,
                category=ErrorCategory.TIMEOUT,
            ) from exc
        except httpx.RequestError as exc:
            raise ProjectError(
                ErrorCode.UNAVAILABLE,
                f"{self.source} is unavailable",
                {"source": self.source},
                cause=exc,
                category=ErrorCategory.RETRYABLE,
            ) from exc
        if response.status_code == 429:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                f"{self.source} rate limit exceeded",
                {"source": self.source},
                category=ErrorCategory.RETRYABLE,
            )
        if response.status_code >= 500:
            raise ProjectError(
                ErrorCode.UNAVAILABLE,
                f"{self.source} returned a server error",
                {"source": self.source, "status_code": response.status_code},
                category=ErrorCategory.RETRYABLE,
            )
        if response.status_code >= 400:
            raise ProjectError(
                ErrorCode.INVALID_ARGUMENT,
                f"{self.source} rejected the search request",
                {"source": self.source, "status_code": response.status_code},
            )
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                f"{self.source} response exceeded the configured bound",
                {"source": self.source, "max_bytes": MAX_RESPONSE_BYTES},
                category=ErrorCategory.RESOURCE,
            )
        return response

    def _invalid_response(self, exc: Exception) -> ProjectError:
        return ProjectError(
            ErrorCode.UNAVAILABLE,
            f"{self.source} returned an invalid response",
            {"source": self.source},
            cause=exc,
            category=ErrorCategory.SYSTEM,
        )


class CrossrefSearchProvider(_HttpScholarlyProvider):
    source = "crossref"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        mailto: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        super().__init__(client, timeout_seconds=timeout_seconds)
        self._mailto = mailto.strip()

    async def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> ScholarlySearchPage:
        params: dict[str, str | int] = {"query.bibliographic": query, "rows": limit}
        filters = _date_filters(year_from, year_to)
        if filters:
            params["filter"] = ",".join(filters)
        if self._mailto:
            params["mailto"] = self._mailto
        response = await self._get("https://api.crossref.org/works", params=params)
        try:
            message = response.json()["message"]
            works = tuple(self._work(item) for item in message.get("items", []))
            return ScholarlySearchPage(
                self.source,
                query,
                tuple(work for work in works if work.title),
                _optional_int(message.get("total-results")),
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise self._invalid_response(exc) from exc

    def _work(self, item: dict[str, Any]) -> ScholarlyWork:
        doi = _normalize_doi(_text(item.get("DOI")))
        authors = []
        for author in item.get("author", []):
            name = " ".join(
                part
                for part in (_text(author.get("given")), _text(author.get("family")))
                if part
            )
            if name:
                authors.append(name)
        return ScholarlyWork(
            source=self.source,
            external_id=doi or _text(item.get("URL")) or "",
            title=_first_text(item.get("title")),
            abstract=_clean_markup(_text(item.get("abstract"))) or None,
            authors=tuple(authors),
            year=_crossref_year(item),
            venue=_first_text(item.get("container-title")) or None,
            doi=doi,
            url=_text(item.get("URL")) or (f"https://doi.org/{doi}" if doi else None),
            citation_count=_optional_int(item.get("is-referenced-by-count")),
        )


class SemanticScholarSearchProvider(_HttpScholarlyProvider):
    source = "semantic_scholar"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        api_key: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        super().__init__(client, timeout_seconds=timeout_seconds)
        self._api_key = api_key.strip()

    async def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> ScholarlySearchPage:
        params: dict[str, str | int] = {
            "query": query,
            "limit": limit,
            "fields": "paperId,title,abstract,year,venue,authors,citationCount,externalIds,url,openAccessPdf",
        }
        year = _year_range(year_from, year_to)
        if year:
            params["year"] = year
        headers = {"x-api-key": self._api_key} if self._api_key else None
        response = await self._get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params,
            headers=headers,
        )
        try:
            payload = response.json()
            works = tuple(self._work(item) for item in payload.get("data", []))
            return ScholarlySearchPage(
                self.source,
                query,
                tuple(work for work in works if work.title),
                _optional_int(payload.get("total")),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise self._invalid_response(exc) from exc

    def _work(self, item: dict[str, Any]) -> ScholarlyWork:
        external_ids = item.get("externalIds") or {}
        open_pdf = item.get("openAccessPdf") or {}
        return ScholarlyWork(
            source=self.source,
            external_id=_text(item.get("paperId")),
            title=_text(item.get("title")),
            abstract=_text(item.get("abstract")) or None,
            authors=tuple(
                name for author in item.get("authors", []) if (name := _text(author.get("name")))
            ),
            year=_optional_int(item.get("year")),
            venue=_text(item.get("venue")) or None,
            doi=_normalize_doi(_text(external_ids.get("DOI"))),
            url=_text(item.get("url")) or None,
            citation_count=_optional_int(item.get("citationCount")),
            open_access_url=_text(open_pdf.get("url")) or None,
        )


class OpenAlexSearchProvider(_HttpScholarlyProvider):
    source = "openalex"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        api_key: str = "",
        mailto: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        super().__init__(client, timeout_seconds=timeout_seconds)
        self._api_key = api_key.strip()
        self._mailto = mailto.strip()

    async def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> ScholarlySearchPage:
        params: dict[str, str | int] = {"search": query, "per-page": limit}
        filters = _openalex_date_filters(year_from, year_to)
        if filters:
            params["filter"] = ",".join(filters)
        if self._api_key:
            params["api_key"] = self._api_key
        if self._mailto:
            params["mailto"] = self._mailto
        response = await self._get("https://api.openalex.org/works", params=params)
        try:
            payload = response.json()
            works = tuple(self._work(item) for item in payload.get("results", []))
            return ScholarlySearchPage(
                self.source,
                query,
                tuple(work for work in works if work.title),
                _optional_int((payload.get("meta") or {}).get("count")),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise self._invalid_response(exc) from exc

    def _work(self, item: dict[str, Any]) -> ScholarlyWork:
        location = item.get("primary_location") or {}
        open_access = item.get("open_access") or {}
        source = location.get("source") or {}
        doi = _normalize_doi(_text(item.get("doi")))
        return ScholarlyWork(
            source=self.source,
            external_id=_text(item.get("id")).rsplit("/", 1)[-1],
            title=_text(item.get("display_name")),
            abstract=_openalex_abstract(item.get("abstract_inverted_index")),
            authors=tuple(
                name
                for authorship in item.get("authorships", [])
                if (name := _text((authorship.get("author") or {}).get("display_name")))
            ),
            year=_optional_int(item.get("publication_year")),
            venue=_text(source.get("display_name")) or None,
            doi=doi,
            url=_text(location.get("landing_page_url"))
            or (f"https://doi.org/{doi}" if doi else None),
            citation_count=_optional_int(item.get("cited_by_count")),
            open_access_url=_text(location.get("pdf_url"))
            or _text(open_access.get("oa_url"))
            or None,
        )


class ArxivSearchProvider(_HttpScholarlyProvider):
    source = "arxiv"

    async def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> ScholarlySearchPage:
        fetch_limit = min(100, limit * 3 if year_from or year_to else limit)
        response = await self._get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f'all:"{query}"',
                "start": 0,
                "max_results": fetch_limit,
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
        )
        try:
            root = ElementTree.fromstring(response.content)
            total_text = root.findtext(f"{OPENSEARCH}totalResults")
            works = [self._work(entry) for entry in root.findall(f"{ATOM}entry")]
            filtered = [
                work
                for work in works
                if (year_from is None or (work.year or 0) >= year_from)
                and (year_to is None or (work.year or 9999) <= year_to)
            ][:limit]
            return ScholarlySearchPage(
                self.source,
                query,
                tuple(work for work in filtered if work.title),
                _optional_int(total_text),
            )
        except ElementTree.ParseError as exc:
            raise self._invalid_response(exc) from exc

    def _work(self, entry: ElementTree.Element) -> ScholarlyWork:
        identifier = _text(entry.findtext(f"{ATOM}id"))
        published = _text(entry.findtext(f"{ATOM}published"))
        alternate = next(
            (
                _text(link.get("href"))
                for link in entry.findall(f"{ATOM}link")
                if link.get("rel") == "alternate"
            ),
            identifier,
        )
        return ScholarlyWork(
            source=self.source,
            external_id=identifier.rsplit("/", 1)[-1],
            title=_collapse_space(entry.findtext(f"{ATOM}title")),
            abstract=_collapse_space(entry.findtext(f"{ATOM}summary")) or None,
            authors=tuple(
                name
                for author in entry.findall(f"{ATOM}author")
                if (name := _collapse_space(author.findtext(f"{ATOM}name")))
            ),
            year=_optional_int(published[:4]),
            venue="arXiv",
            url=alternate or None,
            open_access_url=alternate or None,
        )


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return _text(value[0])
    return _text(value)


def _collapse_space(value: Any) -> str:
    return " ".join(_text(value).split())


def _clean_markup(value: str) -> str:
    return _collapse_space(re.sub(r"<[^>]+>", " ", value))


def _normalize_doi(value: str) -> str | None:
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I).strip()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", normalized, flags=re.I):
        return None
    return normalized.casefold()


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _crossref_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            return _optional_int(parts[0][0])
    return None


def _openalex_abstract(index: Any) -> str | None:
    if not isinstance(index, dict):
        return None
    positioned = sorted(
        (position, word)
        for word, positions in index.items()
        for position in positions
        if isinstance(position, int)
    )
    return " ".join(word for _, word in positioned) or None


def _date_filters(year_from: int | None, year_to: int | None) -> list[str]:
    filters: list[str] = []
    if year_from is not None:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to is not None:
        filters.append(f"until-pub-date:{year_to}-12-31")
    return filters


def _openalex_date_filters(year_from: int | None, year_to: int | None) -> list[str]:
    filters: list[str] = []
    if year_from is not None:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if year_to is not None:
        filters.append(f"to_publication_date:{year_to}-12-31")
    return filters


def _year_range(year_from: int | None, year_to: int | None) -> str:
    if year_from is not None and year_to is not None:
        return f"{year_from}-{year_to}"
    if year_from is not None:
        return f"{year_from}-"
    if year_to is not None:
        return f"-{year_to}"
    return ""
