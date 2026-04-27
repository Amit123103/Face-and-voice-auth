"""
Document Management Router — Handles secure uploads and downloads.
"""

import os
import shutil
import uuid
from typing import List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
import io
import base64
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.models.document import Document
from backend.routers.auth import get_current_user
from backend.schemas.user_data import DocumentResponse
from backend.services.encryption_service import encryption_service

router = APIRouter(prefix="/api/documents", tags=["Documents"])

UPLOAD_DIR = Path("backend/data/user_documents")

@router.on_event("startup")
async def ensure_upload_dir():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Securely uploads a document."""
    # Basic constraints: Reject large files
    # Note: A real streaming file limit is handled via middleware, but typically ~10MB is safe for this POC
    
    uid = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    safe_filename = f"{current_user.id}_{uid}{ext}"
    file_path = UPLOAD_DIR / safe_filename
    
    try:
        # Read file content
        plaintext = await file.read()
        
        # Encrypt content
        ciphertext, nonce = encryption_service.encrypt_binary(
            plaintext, 
            current_user.id, 
            current_user.encryption_salt
        )
        
        # Save encrypted content
        with open(file_path, "wb") as buffer:
            buffer.write(ciphertext)
            
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")
        
        doc = Document(
            id=uid,
            user_id=current_user.id,
            filename=file.filename,
            storage_path=str(file_path),
            content_type=file.content_type or "application/octet-stream",
            file_size=len(plaintext), 
            nonce_b64=nonce_b64
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        
        return doc
        
    except Exception as e:
        if file_path.exists():
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List out user's uploaded documents."""
    result = await db.execute(
        select(Document).where(Document.user_id == current_user.id).order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream file back to user."""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    
    if not doc or not Path(doc.storage_path).exists():
        raise HTTPException(status_code=404, detail="Document not found")
        
    try:
        # Read encrypted bytes
        with open(doc.storage_path, "rb") as f:
            ciphertext = f.read()
            
        # Decrypt
        nonce = base64.b64decode(doc.nonce_b64)
        plaintext = encryption_service.decrypt_binary(
            ciphertext, 
            nonce, 
            current_user.id, 
            current_user.encryption_salt
        )
        
        # Stream back decrypted content
        return StreamingResponse(
            io.BytesIO(plaintext),
            media_type=doc.content_type,
            headers={"Content-Disposition": f"attachment; filename={doc.filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Decryption failed during download")


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document."""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    try:
        if Path(doc.storage_path).exists():
            os.remove(doc.storage_path)
    except OSError:
        pass
        
    await db.delete(doc)
    await db.commit()
    
    return {"message": "Document deleted"}
