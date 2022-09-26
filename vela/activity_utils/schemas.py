from cosmos_message_lib.schemas import utc_datetime
from pydantic import BaseModel, validator

from vela.enums import LoyaltyTypes


class EarnedSchema(BaseModel):
    value: str
    type: LoyaltyTypes

    @validator("type")
    @classmethod
    def convert_type(cls, value: LoyaltyTypes) -> str:
        return value.name


class ProcessedTXEventSchema(BaseModel):
    transaction_id: str
    datetime: utc_datetime
    amount: str
    amount_currency: str
    store_name: str
    earned: list[EarnedSchema]
    mid: str
