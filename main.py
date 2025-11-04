from __future__ import annotations
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi import Query, Path
from typing import Dict, List, Optional

from models.order import (
    OrderCreate,
    OrderRead,
    OrderStatus,
    OrderStatusUpdate
)
from models.log import (
    OrderLogRead
)

port = int(os.environ.get("FASTAPIPORT", 8000))

# -----------------------------------------------------------------------------
# Fake in-memory "databases"
# -----------------------------------------------------------------------------
# Stores OrderRead objects, keyed by order ID (int)
orders: Dict[int, OrderRead] = {}
# Stores a list of OrderLogRead objects for each order ID (int)
order_logs: Dict[int, List[OrderLogRead]] = {}

# Simple auto-incrementing counters for IDs
_order_id_counter = 100
_log_id_counter = 2000

app = FastAPI(
    title="Order & Rental Service API",
    description="This is the Order & Rental Service API for the Luxury Fashion Rental Platform.",
    version="1.0.0",
)


# -----------------------------------------------------------------------------
# Helper Function
# -----------------------------------------------------------------------------

def _create_log(
        order_id: int,
        from_status: OrderStatus,
        to_status: OrderStatus
) -> OrderLogRead:
    """Internal helper to create and store an order log."""
    global _log_id_counter
    _log_id_counter += 1
    new_log_id = _log_id_counter

    log_entry = OrderLogRead(
        log_id=new_log_id,
        order_id=order_id,
        from_status=from_status,
        to_status=to_status,
        timestamp=datetime.utcnow()
    )

    if order_id not in order_logs:
        order_logs[order_id] = []
    order_logs[order_id].append(log_entry)
    return log_entry


# -----------------------------------------------------------------------------
# Order Endpoints
# -----------------------------------------------------------------------------

@app.post("/orders", response_model=OrderRead, status_code=201, tags=["users"])
def create_order(order: OrderCreate):
    """Creates a new rental order for a selected catalog item."""
    global _order_id_counter
    _order_id_counter += 1
    new_id = _order_id_counter

    now = datetime.utcnow()

    # In a real app, total_rent and deposit would be calculated here
    new_order = OrderRead(
        **order.model_dump(),
        id=new_id,
        status=OrderStatus.PENDING,  # New orders default to pending
        created_at=now,
        updated_at=now,
        total_rent=499.99,  # Example fixed value
        deposit=1000.00  # Example fixed value
    )

    orders[new_id] = new_order

    # Log the creation event
    _create_log(new_id, from_status=OrderStatus.PENDING, to_status=OrderStatus.PENDING)

    return new_order


@app.get("/orders", response_model=List[OrderRead], tags=["users"])
def list_orders(
        status: Optional[OrderStatus] = Query(None, description="Filter orders by status"),
        user_id: Optional[int] = Query(None, description="(Admin only) Filter orders by user ID")
):
    """Retrieves all rental orders, with optional filtering."""
    results = list(orders.values())

    if status:
        results = [o for o in results if o.status == status]
    if user_id:
        # In a real app, you'd check user auth here to see if they are an admin
        results = [o for o in results if o.user_id == user_id]

    return results


@app.get("/orders/{orderId}", response_model=OrderRead, tags=["users"])
def get_order_by_id(
        orderId: int = Path(..., description="ID of the order to fetch")
):
    """Retrieves detailed information of a specific order by ID."""
    if orderId not in orders:
        raise HTTPException(status_code=404, detail="Order not found")
    return orders[orderId]


@app.delete("/orders/{orderId}", status_code=200, tags=["users"])
def cancel_order(
        orderId: int = Path(..., description="ID of the order to cancel")
):
    """Cancels an order if its status is still pending."""
    if orderId not in orders:
        raise HTTPException(status_code=404, detail="Order not found")

    order = orders[orderId]

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel non-pending order"
        )

    old_status = order.status
    order.status = OrderStatus.CANCELLED
    order.updated_at = datetime.utcnow()

    # Log the cancellation
    _create_log(order.id, from_status=old_status, to_status=order.status)

    return {"message": "Order cancelled successfully"}


@app.patch("/orders/{orderId}/status", response_model=OrderRead, tags=["admins"])
def update_order_status(
        status_update: OrderStatusUpdate,
        orderId: int = Path(..., description="ID of the order to update")
):
    """Allows admin to update the status of an order."""
    if orderId not in orders:
        raise HTTPException(status_code=404, detail="Order not found")

    order = orders[orderId]
    old_status = order.status
    new_status = status_update.new_status

    # Basic state transition validation
    if old_status in [OrderStatus.CANCELLED, OrderStatus.RETURNED]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition: cannot update order from terminal state '{old_status.value}'"
        )

    if old_status != new_status:
        order.status = new_status
        order.updated_at = datetime.utcnow()
        # Log the change
        _create_log(order.id, from_status=old_status, to_status=new_status)

    return order


@app.get("/orders/{orderId}/logs", response_model=List[OrderLogRead], tags=["admins"])
def get_order_logs(
        orderId: int = Path(..., description="ID of the order")
):
    """Fetches the audit log for status transitions of a specific order."""
    if orderId not in orders:
        # Check if the order itself exists
        raise HTTPException(status_code=404, detail="Order not found")

    return order_logs.get(orderId, [])


# -----------------------------------------------------------------------------
# Root
# -----------------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "Welcome to the Order & Rental Service API. See /docs for OpenAPI UI."}


# -----------------------------------------------------------------------------
# Entrypoint for `python main.py`
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
