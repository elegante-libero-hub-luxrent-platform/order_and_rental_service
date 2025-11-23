from __future__ import annotations

from datetime import date, datetime, UTC
from enum import Enum
from typing import Optional, List, Dict

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    """Enumeration for order status."""
    PENDING = "pending"
    ACTIVE = "active"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class OrderBase(BaseModel):
    """Base model for an order's core data."""
    user_id: int = Field(..., description="ID of the user placing the order.", example=12)
    item_id: int = Field(..., description="ID of the catalog item being rented.", example=505)
    start_date: date = Field(
        ...,
        description="Rental start date (YYYY-MM-DD).",
        example="2025-05-01"
    )
    end_date: date = Field(
        ...,
        description="Rental end date (YYYY-MM-DD).",
        example="2025-05-07"
    )


class OrderCreate(OrderBase):
    """
    Payload for creating a new rental order.
    This matches the 'OrderRequest' schema from the OpenAPI spec.
    """
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": 12,
                    "item_id": 505,
                    "start_date": "2025-05-01",
                    "end_date": "2025-05-07"
                }
            ]
        }
    }


class OrderRead(OrderBase):
    """
    Full representation of an order as returned by the API.
    This matches the 'Order' schema from the OpenAPI spec.
    """
    id: int = Field(..., description="Unique order ID.", example=101)
    total_rent: Optional[float] = Field(
        None,
        description="Total rental cost calculated by the server.",
        example=499.99
    )
    deposit: Optional[float] = Field(
        None,
        description="Deposit amount held for the rental.",
        example=1000.00
    )
    status: OrderStatus = Field(
        ...,
        description="Current status of the order.",
        example=OrderStatus.PENDING
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp (UTC).",
        example="2025-04-28T10:30:00Z"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp (UTC).",
        example="2025-04-29T14:00:00Z"
    )

    links: Optional[Dict[str, str]] = Field(
        default=None,
        description="Related resource links for this order, including self, user, and item.",
        example={
            "self": "/orders/101",
            "user": "/users/12",
            "item": "/items/505",
        },
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 101,
                    "user_id": 12,
                    "item_id": 505,
                    "start_date": "2025-05-01",
                    "end_date": "2025-05-07",
                    "total_rent": 499.99,
                    "deposit": 1000.00,
                    "status": "pending",
                    "created_at": "2025-04-28T10:30:00Z",
                    "updated_at": "2025-04-29T14:00:00Z",
                    "links": {
                        "self": "/orders/101",
                        "user": "/users/12",
                        "item": "/items/505",
                    }
                }
            ]
        }
    }


class OrderStatusUpdate(BaseModel):
    """Payload for the PATCH /orders/{orderId}/status endpoint."""
    new_status: OrderStatus = Field(..., description="The new status to set for the order.")