from pydantic import BaseModel


class OrganizeRequest(BaseModel):
    book_ids: list[int]


class OrganizePreviewItem(BaseModel):
    book_id: int
    title: str | None
    author: str | None
    source_path: str
    destination_path: str


class OrganizePreviewResponse(BaseModel):
    items: list[OrganizePreviewItem]


class OrganizeStatusResponse(BaseModel):
    book_id: int
    organize_status: str
    files_copied: int
    files_total: int
    files_failed: int


class PurgeVerifyItem(BaseModel):
    book_id: int
    title: str | None
    author: str | None
    verified: bool
    missing_files: list[str]
    total_size: int


class PurgeVerifyResponse(BaseModel):
    items: list[PurgeVerifyItem]


class PurgeRequest(BaseModel):
    book_ids: list[int]


class PurgeResultItem(BaseModel):
    book_id: int
    success: bool
    files_deleted: int
    error: str | None


class PurgeResponse(BaseModel):
    results: list[PurgeResultItem]
