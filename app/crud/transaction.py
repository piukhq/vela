from typing import TYPE_CHECKING, List

from sqlalchemy.exc import IntegrityError

from app.db.base_class import retry_query
from app.enums import HttpErrors
from app.models import ProcessedTransaction, RetailerRewards, Transaction

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_transaction(db_session: "Session", retailer: RetailerRewards, transaction_data: dict) -> Transaction:
    with retry_query(session=db_session):
        transaction = Transaction(retailer_id=retailer.id, **transaction_data)
        try:
            db_session.add(transaction)
            db_session.commit()
        except IntegrityError:
            raise HttpErrors.DUPLICATE_TRANSACTION.value

    return transaction


def delete_transaction(db_session: "Session", transaction: Transaction) -> None:
    with retry_query(session=db_session):
        db_session.delete(transaction)
        db_session.commit()


def create_processed_transaction(
    db_session: "Session", retailer: RetailerRewards, campaign_slugs: List[str], transaction_data: dict
) -> ProcessedTransaction:
    with retry_query(session=db_session):
        processed_transaction = ProcessedTransaction(
            retailer_id=retailer.id, campaign_slugs=campaign_slugs, **transaction_data
        )
        try:
            db_session.add(processed_transaction)
            db_session.commit()
        except IntegrityError:
            raise HttpErrors.DUPLICATE_TRANSACTION.value

    return processed_transaction
