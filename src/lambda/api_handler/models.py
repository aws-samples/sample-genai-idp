"""Request and Response models for the Jobs API."""

from typing import Dict, Optional

from pydantic import BaseModel


# Request Models
class Metadata(BaseModel):
    source: str

class PostJobRequest(BaseModel):
    fileName: str  # Filename with extension (.zip)
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
    timestamps: Timestamps
    files: Optional[Dict[str, str]] = None
    result: Optional[Result] = None
    error: Optional[str] = None
