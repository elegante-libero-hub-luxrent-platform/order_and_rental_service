from __future__ import annotations

from datetime import datetime, UTC
from pydantic import BaseModel, Field

# Import status enum from the other model file
from .order import OrderStatus


class OrderLogBase(BaseModel):
    """Base model for an order log entry."""
    order_id: int = Field(..., description="The ID of the order this log belongs to.", example=101)
    from_status: OrderStatus = Field(..., description="The status before the change.", example="pending")
    to_status: OrderStatus = Field(..., description="The status after the change.", example="active")


class OrderLogCreate(OrderLogBase):
    """Payload for creating a new log (used internally)."""
    pass


class OrderLogRead(OrderLogBase):
    """
    Full representation of an order log as returned by the API.
    This matches the 'OrderLog' schema from the OpenAPI spec.
    """
    log_id: int = Field(..., description="Unique ID for the log entry.", example=2001)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of when the status change occurred (UTC).",
        example="2025-05-02T09:00:00Z"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "log_id": 2001,
                    "order_id": 101,
                    "from_status": "pending",
                    "to_status": "active",
                    "timestamp": "2025-05-02T09:00:00Z"
                }
            ]
        }
    }