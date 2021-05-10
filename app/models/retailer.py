from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, text
from sqlalchemy.orm import relationship

from app.db.base_class import Base
from app.enums import CampaignStatuses


class RetailerRewards(Base):
    __tablename__ = "retailer_rewards"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(32), index=True, unique=True, nullable=False)

    campaigns = relationship("Campaign", back_populates="retailer")

    __mapper_args__ = {"eager_defaults": True}

    def __str__(self) -> str:
        return str(self.name)  # pragma: no cover


class Campaign(Base):
    __tablename__ = "campaign"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(Enum(CampaignStatuses), nullable=False, server_default="DRAFT")
    name = Column(String(128), nullable=False)
    slug = Column(String(32), index=True, unique=True, nullable=False)
    created_at = Column(DateTime, server_default=text("TIMEZONE('utc', CURRENT_TIMESTAMP)"), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=text("TIMEZONE('utc', CURRENT_TIMESTAMP)"),
        onupdate=text("TIMEZONE('utc', CURRENT_TIMESTAMP)"),
        nullable=False,
    )
    retailer_id = Column(Integer, ForeignKey("retailer_rewards.id", ondelete="CASCADE"))

    retailer = relationship("RetailerRewards", back_populates="campaigns")

    def __str__(self) -> str:  # pragma: no cover
        return str(self.name)
