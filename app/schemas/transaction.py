from pydantic import BaseModel, Field, validator
from pydantic.types import UUID4


class CreateTransactionSchema(BaseModel):  # pragma: no cover
    transaction_id: str = Field(..., alias="id")
    amount: float = Field(..., alias="transaction_total")
    datetime: int
    mid: str = Field(..., alias="MID")
    account_holder_uuid: UUID4 = Field(..., alias="loyalty_id")

    @validator("amount")
    @classmethod
    def get_float(cls, v: float) -> int:
        return int(v * 100)
