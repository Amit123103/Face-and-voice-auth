"""
Pydantic schemas for Document and Secret Vault endpoints.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    file_size: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class VaultCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    category: str = Field("Personal", max_length=50)
    secret_type: str = Field("Note", max_length=50)


class VaultUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    category: str = Field(..., max_length=50)
    secret_type: str = Field(..., max_length=50)


class VaultListResponse(BaseModel):
    id: str
    title: str
    category: str
    secret_type: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class VaultDetailResponse(VaultListResponse):
    content: str
