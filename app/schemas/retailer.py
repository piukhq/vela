from datetime import datetime

from pydantic import BaseModel, Field, validator

from app.enums import CampaignStatuses


class CampaignSchema(BaseModel):
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
