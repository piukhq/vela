from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.db.base_class import retry_query
from app.enums import HttpErrors
from app.internal_requests import validate_account_holder_uuid
from app.models import RetailerRewards, Transaction
from app.schemas import CreateTransactionSchema

router = APIRouter()


@router.post(
    path="/{retailer_slug}/transaction",
    response_model=str,
    dependencies=[Depends(user_is_authorised)],
)
async def record_transaction(
    payload: CreateTransactionSchema,
    retailer: RetailerRewards = Depends(retailer_is_valid),
    db_session: Session = Depends(get_session),
) -> Any:
    validate_account_holder_uuid(payload.account_holder_uuid, retailer.slug)

    with retry_query(session=db_session):
        try:
            db_session.add(Transaction(retailer_id=retailer.id, **payload.dict(exclude_unset=True)))  # type: ignore
            db_session.commit()
        except IntegrityError:
            raise HttpErrors.DUPLICATE_TRANSACTION.value

        return "Processed"
