from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud
from app.api.deps import get_session, retailer_is_valid, user_is_authorised
from app.internal_requests import validate_account_holder_uuid
from app.models import RetailerRewards
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
    transaction_data = payload.dict(exclude_unset=True)
    transaction = crud.create_transaction(db_session, retailer, transaction_data)
    active_campaign_slugs = crud.get_active_campaign_slugs(db_session, retailer)

    if crud.check_earn_rule_for_campaigns(db_session, transaction, active_campaign_slugs):
        response = "Awarded"
    else:
        response = "Threshold not met"

    crud.create_processed_transaction(db_session, retailer, active_campaign_slugs, transaction_data)
    crud.delete_transaction(db_session, transaction)

    return response
