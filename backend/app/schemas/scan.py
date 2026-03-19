from datetime import datetime

from pydantic import BaseModel


class ScanCreate(BaseModel):
    source_dir: str


class ScannedFolderResponse(BaseModel):
    id: int
    scan_id: int
    folder_path: str
    folder_name: str
    status: str
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanResponse(BaseModel):
    id: int
    source_dir: str
    status: str
    total_folders: int
    processed_folders: int
    error_message: str | None
    status_detail: str | None = None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ScanDetailResponse(ScanResponse):
    folders: list[ScannedFolderResponse]
