"""List pagination (architecture section 4): ``?page=1&page_size=20``."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Query

PageParam = Annotated[int, Query(ge=1)]
PageSizeParam = Annotated[int, Query(ge=1, le=100)]


def page_meta(total: int, page: int, page_size: int) -> dict[str, Any]:
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
