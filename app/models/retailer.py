from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Numeric
from sqlalchemy.orm import relationship

from app.db.base_class import Base, TimestampMixin
from app.enums import CampaignStatuses

if TYPE_CHECKING:  # pragma: no cover
    from .transaction import Transaction  # noqa 401


class RetailerRewards(Base):
    __tablename__ = "retailer_rewards"

    slug = Column(String(32), index=True, unique=True, nullable=False)

    campaigns = relationship("Campaign", back_populates="retailer")
    transactions = relationship("Transaction", back_populates="retailer")

    __mapper_args__ = {"eager_defaults": True}

    def __str__(self) -> str:
        return str(self.slug)  # pragma: no cover


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaign"

    status = Column(Enum(CampaignStatuses), nullable=False, server_default="DRAFT")
    name = Column(String(128), nullable=False)
    slug = Column(String(32), index=True, unique=True, nullable=False)
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"), nullable=False)
    earn_inc_is_tx_value = Column(Boolean, default=False, nullable=False)

    retailer = relationship("RetailerRewards", back_populates="campaigns")
    earn_rules = relationship("EarnRule", back_populates="campaign")

    def __str__(self) -> str:  # pragma: no cover
        return str(self.name)


class EarnRule(Base, TimestampMixin):
    __tablename__ = "earn_rule"

    threshold = Column(Integer, nullable=False)
    increment = Column(Integer, nullable=True)
    increment_multiplier = Column(Numeric(scale=2), default=1, nullable=False)

    campaign_id = Column(Integer, ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False)
    campaign = relationship("Campaign", back_populates="earn_rules")
