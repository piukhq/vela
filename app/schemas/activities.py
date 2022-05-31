from datetime import datetime as dt

from pydantic import BaseModel, validator

from app.enums import LoyaltyTypes


class EarnedSchema(BaseModel):
    value: str
    type: LoyaltyTypes

    @validator("type")
    @classmethod
    def convert_type(cls, value: LoyaltyTypes) -> str:
        return value.name


class ProcessedTXEventSchema(BaseModel):
    transaction_id: str
    datetime: dt
    amount: str
    amount_currency: str
    store_name: str
    earned: list[EarnedSchema]
    mid: str
