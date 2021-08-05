from datetime import datetime as dt

from pydantic import BaseModel, Field, StrictInt, constr, validator
from pydantic.types import UUID4


# I pass in an empty string for any of these fields: id, datetime, MID or loyalty_id
class CreateTransactionSchema(BaseModel):  # pragma: no cover
    transaction_id: constr(strip_whitespace=True, min_length=1) = Field(..., alias="id")  # type: ignore
    amount: StrictInt = Field(..., alias="transaction_total")
    datetime: float
    mid: constr(strip_whitespace=True, min_length=1) = Field(..., alias="MID")  # type: ignore
    account_holder_uuid: UUID4 = Field(..., alias="loyalty_id")

    @validator("datetime")
    @classmethod
    def get_datetime_from_timestamp(cls, v: int) -> dt:
        try:
            processed_datetime = dt.fromtimestamp(v)
        except Exception:
            raise ValueError("invalid datetime")

        return processed_datetime
