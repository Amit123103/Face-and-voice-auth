"""
Transaction Router — dual-biometric payment transactions.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.models.transaction import Transaction, TransactionStatus
from backend.routers.auth import get_current_user
from backend.schemas.transaction import TransactionCreateRequest, TransactionResponse, TransactionFaceVerifyRequest
from backend.services.face_service import face_service

router = APIRouter(prefix="/api/transactions", tags=["Transactions"])


@router.post("/", response_model=TransactionResponse)
async def create_transaction(
    data: TransactionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Initiate a peer-to-peer payment transaction to an email."""
    if data.receiver_email.lower() == current_user.email.lower():
        raise HTTPException(status_code=400, detail="Cannot send money to yourself")

    if current_user.balance < data.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    # Find receiver
    receiver_result = await db.execute(select(User).where(User.email == data.receiver_email))
    receiver = receiver_result.scalar_one_or_none()

    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    txn = Transaction(
        sender_id=current_user.id,
        receiver_id=receiver.id,
        amount=data.amount,
        status=TransactionStatus.PENDING,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    return TransactionResponse(
        id=txn.id,
        sender_email=current_user.email,
        receiver_email=receiver.email,
        amount=txn.amount,
        status=txn.status,
        sender_face_verified=txn.sender_face_verified,
        receiver_face_verified=txn.receiver_face_verified,
        admin_approved=txn.admin_approved,
        created_at=txn.created_at,
    )


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List transactions sent or received by the current user."""
    result = await db.execute(
        select(Transaction, User.email.label("sender_email"))
        .join(User, User.id == Transaction.sender_id)
        .where(or_(Transaction.sender_id == current_user.id, Transaction.receiver_id == current_user.id))
        .order_by(Transaction.created_at.desc())
    )

    # We need to manually construct the response object by fetching the receiver emails too
    transactions = result.all()

    response_list = []
    for txn, sender_email in transactions:
        # Get receiver email
        rx = await db.execute(select(User.email).where(User.id == txn.receiver_id))
        rx_email = rx.scalar_one()

        response_list.append(TransactionResponse(
            id=txn.id,
            sender_email=sender_email,
            receiver_email=rx_email,
            amount=txn.amount,
            status=txn.status,
            sender_face_verified=txn.sender_face_verified,
            receiver_face_verified=txn.receiver_face_verified,
            admin_approved=txn.admin_approved,
            created_at=txn.created_at,
        ))

    return response_list


@router.patch("/{txn_id}/verify-sender", response_model=TransactionResponse)
async def verify_sender(
    txn_id: str,
    data: TransactionFaceVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sender verifies identity to authorize sending."""
    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = result.scalar_one_or_none()

    if not txn or txn.sender_id != current_user.id:
        raise HTTPException(status_code=404, detail="Transaction not found or you are not the sender")

    if txn.sender_face_verified:
        raise HTTPException(status_code=400, detail="Sender already verified")

    try:
        is_match, conf, _, msg = await face_service.verify_face(data.frames, current_user.id, db)
        if not is_match:
            raise HTTPException(status_code=401, detail="Face verification failed")

        txn.sender_face_verified = True
        if txn.receiver_face_verified:
            txn.status = TransactionStatus.RECEIVER_VERIFIED
        else:
            txn.status = TransactionStatus.SENDER_VERIFIED

        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await get_transaction_response(db, txn)


@router.patch("/{txn_id}/verify-receiver", response_model=TransactionResponse)
async def verify_receiver(
    txn_id: str,
    data: TransactionFaceVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Receiver verifies identity to authorize receiving."""
    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = result.scalar_one_or_none()

    if not txn or txn.receiver_id != current_user.id:
        raise HTTPException(status_code=404, detail="Transaction not found or you are not the receiver")

    if txn.receiver_face_verified:
        raise HTTPException(status_code=400, detail="Receiver already verified")

    try:
        is_match, conf, _, msg = await face_service.verify_face(data.frames, current_user.id, db)
        if not is_match:
            raise HTTPException(status_code=401, detail="Face verification failed")

        txn.receiver_face_verified = True

        # We only really advance status if sender has ALSO verified, meaning it's ready for admin.
        # But for logic simplicity:
        if txn.sender_face_verified:
            txn.status = TransactionStatus.RECEIVER_VERIFIED  # Means both are verified, ready for admin

        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await get_transaction_response(db, txn)


async def get_transaction_response(db: AsyncSession, txn: Transaction) -> TransactionResponse:
    sender = await db.execute(select(User.email).where(User.id == txn.sender_id))
    receiver = await db.execute(select(User.email).where(User.id == txn.receiver_id))

    return TransactionResponse(
        id=txn.id,
        sender_email=sender.scalar_one(),
        receiver_email=receiver.scalar_one(),
        amount=txn.amount,
        status=txn.status,
        sender_face_verified=txn.sender_face_verified,
        receiver_face_verified=txn.receiver_face_verified,
        admin_approved=txn.admin_approved,
        created_at=txn.created_at,
    )
