from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from vela.db.base_class import Base, TimestampMixin
from vela.enums import CampaignStatuses, LoyaltyTypes, RetailerStatuses, RewardCap

if TYPE_CHECKING:  # pragma: no cover
    from .transaction import ProcessedTransaction, Transaction  # noqa 401


class RetailerRewards(Base):
    __tablename__ = "retailer_rewards"

    slug = Column(String(32), index=True, unique=True, nullable=False)
    status = Column(Enum(RetailerStatuses), nullable=False, index=True, default=RetailerStatuses.TEST)

    campaigns = relationship("Campaign", back_populates="retailer")
    transactions = relationship("Transaction", back_populates="retailer")
    processed_transactions = relationship("ProcessedTransaction", back_populates="retailer")
    stores = relationship("RetailerStore", back_populates="retailer")

    __mapper_args__: ClassVar[dict] = {"eager_defaults": True}

    def __str__(self) -> str:
        return str(self.slug)  # pragma: no cover


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaign"

    status = Column(Enum(CampaignStatuses), nullable=False, server_default="DRAFT")
    name = Column(String(128), nullable=False)
    slug = Column(String(100), index=True, unique=True, nullable=False)
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"), nullable=False)
    loyalty_type = Column(Enum(LoyaltyTypes), nullable=False, server_default="STAMPS")
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    retailer = relationship("RetailerRewards", back_populates="campaigns")
    earn_rules = relationship("EarnRule", cascade="all,delete", back_populates="campaign")
    reward_rule = relationship("RewardRule", cascade="all,delete", back_populates="campaign", uselist=False)

    def __str__(self) -> str:  # pragma: no cover
        return str(self.name)

    def is_activable(self) -> bool:
        return self.status == CampaignStatuses.DRAFT and self.reward_rule is not None and len(self.earn_rules) >= 1


class EarnRule(Base, TimestampMixin):
    __tablename__ = "earn_rule"

    threshold = Column(Integer, nullable=False)
    increment = Column(Integer, nullable=True)
    increment_multiplier = Column(Numeric(scale=2), default=1, nullable=False)
    max_amount = Column(Integer, nullable=False, server_default="0")

    campaign_id = Column(Integer, ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False)
    campaign = relationship("Campaign", back_populates="earn_rules")


class RewardRule(Base, TimestampMixin):
    __tablename__ = "reward_rule"

    reward_goal = Column(Integer, nullable=False)
    reward_slug = Column(String(32), index=True, unique=False, nullable=False)
    allocation_window = Column(Integer, nullable=False, server_default="0")
    reward_cap = Column(Enum(RewardCap, values_callable=lambda _: [str(e.value) for e in RewardCap]), nullable=True)

    campaign_id = Column(Integer, ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False)
    campaign = relationship("Campaign", back_populates="reward_rule")


class RetailerStore(Base, TimestampMixin):
    __tablename__ = "retailer_store"

    store_name = Column(String, nullable=False)
    mid = Column(String, nullable=False, unique=True)
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"), nullable=False)

    retailer = relationship("RetailerRewards", back_populates="stores")
