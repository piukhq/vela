from datetime import datetime as dt

from pydantic import BaseModel, Field, StrictInt, validator
from pydantic.types import UUID4


# I pass in an empty string for any of these fields: id, datetime, MID or loyalty_id
class CreateTransactionSchema(BaseModel):  # pragma: no cover
    transaction_id: str = Field(..., alias="id", min_length=1)
    amount: StrictInt = Field(..., alias="transaction_total")
    datetime: float
    mid: str = Field(..., alias="MID", min_length=1)
    account_holder_uuid: UUID4 = Field(..., alias="loyalty_id")

    @validator("datetime")
    @classmethod
    def get_datetime_from_timestamp(cls, v: int) -> dt:
        try:
            processed_datetime = dt.fromtimestamp(v)
        except Exception:
            raise ValueError("invalid datetime")

        return processed_datetime
