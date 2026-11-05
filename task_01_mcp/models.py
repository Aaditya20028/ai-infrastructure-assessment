"""One source of truth for published schemas and runtime validation."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

CustomerId = Annotated[str, Field(pattern=r"^CUST-[0-9]{5}$")]
RefundAmount = Annotated[float, Field(gt=0, allow_inf_nan=False)]
RefundReason = Annotated[str, Field(min_length=10)]


class CustomerLookup(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    customer_id: CustomerId


class RefundRequest(CustomerLookup):
    amount: RefundAmount
    reason: RefundReason
