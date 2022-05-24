from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base, TimestampMixin
from app.enums import TransactionProcessingStatuses

if TYPE_CHECKING:  # pragma: no cover
    from .retailer import RetailerRewards  # noqa 401


class Transaction(Base, TimestampMixin):
    __tablename__ = "transaction"

    transaction_id = Column(String(128), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    mid = Column(String(128), nullable=False)
    datetime = Column(DateTime, nullable=False)
    account_holder_uuid = Column(UUID(as_uuid=True), nullable=False)
    payment_transaction_id = Column(String(128), nullable=True, index=True)
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"))
    status = Column(Enum(TransactionProcessingStatuses), nullable=True, index=True)

    retailer = relationship("RetailerRewards", back_populates="transactions")

    __table_args__ = (UniqueConstraint("transaction_id", "retailer_id", name="transaction_retailer_unq"),)
    __mapper_args__ = {"eager_defaults": True}


class ProcessedTransaction(Base, TimestampMixin):
    __tablename__ = "processed_transaction"

    transaction_id = Column(String(128), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    mid = Column(String(128), nullable=False)
    datetime = Column(DateTime, nullable=False)
    account_holder_uuid = Column(UUID(as_uuid=True), nullable=False)
    payment_transaction_id = Column(String(128), nullable=True, index=True)
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"))
    campaign_slugs = Column(ARRAY(String(128)), nullable=False)

    retailer = relationship("RetailerRewards", back_populates="processed_transactions")

    __table_args__ = (UniqueConstraint("transaction_id", "retailer_id", name="process_transaction_retailer_unq"),)
    __mapper_args__ = {"eager_defaults": True}
