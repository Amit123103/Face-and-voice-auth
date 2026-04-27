"""
Secure Vault Router — End-to-end encryption for user secrets.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.models.vault import SecretVault
from backend.routers.auth import get_current_user
from backend.schemas.user_data import VaultCreateRequest, VaultUpdateRequest, VaultListResponse, VaultDetailResponse
from backend.services.encryption_service import encryption_service

router = APIRouter(prefix="/api/vault", tags=["Secure Vault"])


@router.post("/", response_model=VaultListResponse, status_code=201)
async def create_secret(
    data: VaultCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Encrypt and store a new secret."""
    try:
        ciphertext_b64, nonce_b64 = encryption_service.encrypt(
            data.content.encode("utf-8"),
            current_user.id,
            current_user.encryption_salt,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Encryption failure")

    secret = SecretVault(
        user_id=current_user.id,
        title=data.title,
        category=data.category,
        secret_type=data.secret_type,
        ciphertext_b64=ciphertext_b64,
        nonce_b64=nonce_b64,
    )
    db.add(secret)
    await db.commit()
    await db.refresh(secret)

    return secret


@router.get("/", response_model=List[VaultListResponse])
async def list_secrets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all secret titles (without decrypting contents)."""
    result = await db.execute(
        select(SecretVault).where(SecretVault.user_id == current_user.id).order_by(SecretVault.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{secret_id}", response_model=VaultDetailResponse)
async def get_secret(
    secret_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve and decrypt a specific secret."""
    result = await db.execute(
        select(SecretVault).where(SecretVault.id == secret_id, SecretVault.user_id == current_user.id)
    )
    secret = result.scalar_one_or_none()
    
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
        
    try:
        plaintext = encryption_service.decrypt(
            secret.ciphertext_b64,
            secret.nonce_b64,
            current_user.id,
            current_user.encryption_salt,
        )
        content = plaintext.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Decryption failure")
        
    return VaultDetailResponse(
        id=secret.id,
        title=secret.title,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
        content=content,
    )


@router.put("/{secret_id}", response_model=VaultListResponse)
async def update_secret(
    secret_id: str,
    data: VaultUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SecretVault).where(SecretVault.id == secret_id, SecretVault.user_id == current_user.id)
    )
    secret = result.scalar_one_or_none()
    
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
        
    try:
        ciphertext_b64, nonce_b64 = encryption_service.encrypt(
            data.content.encode("utf-8"),
            current_user.id,
            current_user.encryption_salt,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Encryption failure")
        
    secret.title = data.title
    secret.category = data.category
    secret.secret_type = data.secret_type
    secret.ciphertext_b64 = ciphertext_b64
    secret.nonce_b64 = nonce_b64
    
    await db.commit()
    await db.refresh(secret)
    return secret


@router.delete("/{secret_id}")
async def delete_secret(
    secret_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SecretVault).where(SecretVault.id == secret_id, SecretVault.user_id == current_user.id)
    )
    secret = result.scalar_one_or_none()
    
    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")
        
    await db.delete(secret)
    await db.commit()
    return {"message": "Secret deleted"}
