from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import relationship

from app.db.base_class import Base, TimestampMixin
from app.enums import RewardAdjustmentStatuses

if TYPE_CHECKING:  # pragma: no cover
    from .retailer import RetailerRewards  # noqa 401


class Transaction(Base, TimestampMixin):
    __tablename__ = "transaction"

    transaction_id = Column(String(128), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    mid = Column(String(128), nullable=False)
    datetime = Column(DateTime, nullable=False)
    account_holder_uuid = Column(UUID(as_uuid=True), nullable=False)
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"))

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
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"))
    campaign_slugs = Column(ARRAY(String(128)), nullable=False)

    retailer = relationship("RetailerRewards", back_populates="processed_transactions")
    reward_adjustments = relationship("RewardAdjustment", back_populates="processed_transaction")

    __table_args__ = (UniqueConstraint("transaction_id", "retailer_id", name="process_transaction_retailer_unq"),)
    __mapper_args__ = {"eager_defaults": True}


class RewardAdjustment(Base, TimestampMixin):
    __tablename__ = "reward_adjustment"

    status = Column(Enum(RewardAdjustmentStatuses), nullable=False, default=RewardAdjustmentStatuses.PENDING)
    attempts = Column(Integer, default=0, nullable=False)
    adjustment_amount = Column(Integer, nullable=False)
    campaign_slug = Column(String, nullable=False)
    next_attempt_time = Column(DateTime, nullable=True)
    response_data = Column(MutableList.as_mutable(JSONB), nullable=False, default=text("'[]'::jsonb"))
    processed_transaction_id = Column(Integer, ForeignKey("processed_transaction.id", ondelete="CASCADE"))

    processed_transaction = relationship("ProcessedTransaction", back_populates="reward_adjustments")

    __mapper_args__ = {"eager_defaults": True}

    def __str__(self) -> str:
        return f"{self.status.value.upper()} RewardAdjustment (id: {self.id})"  # type: ignore [attr-defined]
