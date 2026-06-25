"""Request and Response models for the Jobs API."""

from typing import Dict, Optional

from pydantic import BaseModel, Field


# Request Models
class Metadata(BaseModel):
    source: str

class PostJobRequest(BaseModel):
    fileName: str  # Filename with extension (.zip)
    configurationVersion: Optional[str] = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-zA-Z0-9._-]+$",
        description="Configuration version to use for processing (e.g. 'v1', 'lending-v2')",
    )
    metadata: Optional[Metadata] = None


# Response Models
class UploadInfo(BaseModel):
    uploadUrl: str
    expiresInSeconds: int
    requiredHeaders: Dict[str, str]


class PostJobResponse(BaseModel):
    jobId: str
    upload: UploadInfo


class Timestamps(BaseModel):
    createdAt: str
    updatedAt: str


class Result(BaseModel):
    downloadUrl: str
    expiresInSeconds: int


class GetJobResponse(BaseModel):
    jobId: str
    status: str
    configurationVersion: Optional[str] = None
    timestamps: Timestamps
    files: Optional[Dict[str, str]] = None
    result: Optional[Result] = None
    error: Optional[str] = None
