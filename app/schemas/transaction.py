from datetime import datetime as dt

from pydantic import BaseModel, Field, validator
from pydantic.types import UUID4


class CreateTransactionSchema(BaseModel):  # pragma: no cover
    transaction_id: str = Field(..., alias="id")
    amount: int = Field(..., alias="transaction_total")
    datetime: int
    mid: str = Field(..., alias="MID")
    account_holder_uuid: UUID4 = Field(..., alias="loyalty_id")

    @validator("datetime")
    @classmethod
    def get_datetime_from_timestamp(cls, v: int) -> dt:
        try:
            processed_datetime = dt.fromtimestamp(v)
        except Exception:
            raise ValueError("invalid datetime")

        return processed_datetime
