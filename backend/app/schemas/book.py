from datetime import datetime

from pydantic import BaseModel


class BookFileResponse(BaseModel):
    id: int
    book_id: int
    original_path: str
    filename: str
    file_size: int
    file_format: str | None
    destination_path: str | None
    copy_status: str
    tag_title: str | None
    tag_author: str | None
    tag_album: str | None
    tag_year: str | None
    tag_track: str | None
    tag_narrator: str | None

    model_config = {"from_attributes": True}


class BookResponse(BaseModel):
    id: int
    scanned_folder_id: int | None
    title: str | None
    author: str | None
    series: str | None
    series_position: str | None
    year: str | None
    narrator: str | None
    edition: str | None
    source: str
    confidence: float
    is_confirmed: bool
    output_path: str | None
    organize_status: str
    purge_status: str
    folder_path: str | None = None
    folder_name: str | None = None
    projected_path: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BookDetailResponse(BookResponse):
    files: list[BookFileResponse]


class BookUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    series: str | None = None
    series_position: str | None = None
    year: str | None = None
    narrator: str | None = None
    edition: str | None = None


class BookConfirmBatch(BaseModel):
    book_ids: list[int] | None = None
    min_confidence: float | None = None
    scan_id: int | None = None


class LookupResult(BaseModel):
    provider: str
    title: str | None
    author: str | None
    series: str | None
    series_position: str | None
    year: str | None
    narrator: str | None = None
    description: str | None
    cover_url: str | None
    confidence: float


class LookupResponse(BaseModel):
    results: list[LookupResult]


class ApplyLookup(BaseModel):
    provider: str
    result_index: int


class BookSearch(BaseModel):
    query: str


class PaginatedBooksResponse(BaseModel):
    items: list[BookResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
