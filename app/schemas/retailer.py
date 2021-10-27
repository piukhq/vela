from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, constr, validator

from app.enums import CampaignStatuses


class CampaignSchema(BaseModel):  # pragma: no cover
    id: int
    status: CampaignStatuses
    name: str
    slug: str
    created_at: datetime = Field(..., alias="created_date")
    updated_at: datetime = Field(..., alias="updated_date")

    @validator("created_at")
    @classmethod
    def get_create_at_timestamp(cls, v: datetime) -> int:
        return int(v.timestamp())

    @validator("updated_at")
    @classmethod
    def get_updated_at_timestamp(cls, v: datetime) -> int:
        return int(v.timestamp())

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class CampaignsStatusChangeSchema(BaseModel):  # pragma: no cover
    requested_status: CampaignStatuses
    campaign_slugs: List[constr(strip_whitespace=True, min_length=1)]  # type: ignore
