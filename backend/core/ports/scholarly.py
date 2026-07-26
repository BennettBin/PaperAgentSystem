"""Port contracts for read-only scholarly metadata search providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScholarlyWork:
    source: str
    external_id: str
    title: str
    abstract: str | None = None
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    citation_count: int | None = None
    open_access_url: str | None = None


@dataclass(frozen=True, slots=True)
class ScholarlySearchPage:
    source: str
    query: str
    works: tuple[ScholarlyWork, ...]
    total: int | None = None


class ScholarlySearchProvider(Protocol):
    source: str

    async def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> ScholarlySearchPage: ...
