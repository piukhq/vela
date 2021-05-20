from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from .retailer import RetailerRewards  # noqa 401


class Transaction(Base, TimestampMixin):
    __tablename__ = "transaction"

    transaction_id = Column(String(128), nullable=False, unique=True, index=True)
    amount = Column(Integer, nullable=False)
    mid = Column(String(128), nullable=False)
    datetime = Column(Integer, nullable=False)
    account_holder_uuid = Column(UUID(as_uuid=True), nullable=False)
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"))

    retailer = relationship("RetailerRewards", back_populates="transactions")
