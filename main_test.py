from __future__ import annotations

import os
import uuid
from datetime import datetime, UTC
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query, Response

from models.order import (
    OrderCreate,
    OrderRead,
    OrderStatus,
    OrderStatusUpdate,
)
from models.log import (
    OrderLogRead,
)

# Port configuration for cloud deployment (Cloud Run / VM / bare metal)
port = int(os.environ.get("FASTAPIPORT", 8000))

# In-memory storage for simplicity.
# In a real production system these would be persisted in Cloud SQL.
orders: Dict[int, OrderRead] = {}
order_logs: Dict[int, List[OrderLogRead]] = {}
jobs: Dict[str, Dict] = {}

# Fake auto-incrementing primary key
_order_id_counter = 100

# FastAPI application initialization
app = FastAPI(
    title="Order & Rental Service API",
    description="Manages order lifecycle, async confirmation, filtering, and linked data.",
    version="1.0.0",
)
# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

def _create_log(order_id: int, from_status: OrderStatus, to_status: OrderStatus) -> OrderLogRead:
    """
    Creates a log entry for an order status transition.

    This simulates an audit trail normally stored in a database table.
    """
    log_entry = OrderLogRead(
        log_id=len(order_logs.get(order_id, [])) + 1,
        order_id=order_id,
        from_status=from_status,
        to_status=to_status,
        timestamp=datetime.now(UTC)
    )

    if order_id not in order_logs:
        order_logs[order_id] = []
    order_logs[order_id].append(log_entry)

    return log_entry


def _build_order_links(order: OrderRead) -> Dict[str, str]:
    """
    Builds HATEOAS-style links for this order.

    This makes the API self-descriptive: clients can follow links
    rather than constructing URLs manually.
    """
    return {
        "self": f"/orders/{order.id}",
        "user": f"/users/{order.user_id}",
        "item": f"/items/{order.item_id}",
    }


def _ensure_order_links(order: OrderRead) -> OrderRead:
    """
    Ensure the OrderRead model contains HATEOAS links.
    If missing, compute them.
    """
    if getattr(order, "links", None) is None:
        order.links = _build_order_links(order)
    return order


def _process_confirm_order(order_id: int, job_id: str) -> None:
    """
    Background task that simulates async order confirmation.

    This models long-running workflows such as:
    - inventory checks
    - payment authorization
    - communication with external microservices

    The POST /orders/{id}/confirm endpoint immediately returns 202,
    and this function runs asynchronously after the HTTP request completes.
    """

    job = jobs.get(job_id)
    if job is None:
        return

    job["status"] = "running"
    order = orders.get(order_id)

    if order is None:
        job["status"] = "failed"
        job["result"] = "order_not_found"
        return

    try:
        # Only PENDING orders can be confirmed
        if order.status != OrderStatus.PENDING:
            job["status"] = "failed"
            job["result"] = "invalid_state"
            return

        # Update order state to ACTIVE
        old_status = order.status
        order.status = OrderStatus.ACTIVE
        order.updated_at = datetime.now(UTC)

        # Add a log entry
        _create_log(order.id, from_status=old_status, to_status=order.status)

        _ensure_order_links(order)

        # Mark job succeeded and return the location of the resource
        job["status"] = "succeeded"
        job["result"] = f"/orders/{order.id}"

    except Exception:
        job["status"] = "failed"
        job["result"] = "internal_error"


# ------------------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------------------

@app.post("/orders", response_model=OrderRead, status_code=201, tags=["users"])
def create_order(order: OrderCreate, response: Response):
    """
    Create a new order.

    Returns:
    - HTTP 201 Created (REST standard for resource creation)
    - Location header with the canonical URL of the new resource
    """

    global _order_id_counter
    _order_id_counter += 1
    new_id = _order_id_counter
    now = datetime.now(UTC)

    # Construct the new order record
    new_order = OrderRead(
        **order.model_dump(),
        id=new_id,
        status=OrderStatus.PENDING,
        created_at=now,
        updated_at=now,
        total_rent=499.99,  # Business logic placeholder
        deposit=1000.00,  # Business logic placeholder
    )

    _ensure_order_links(new_order)
    orders[new_id] = new_order

    # Log initial status
    _create_log(new_id, from_status=OrderStatus.PENDING, to_status=OrderStatus.PENDING)

    # Include Location header for new resource
    response.headers["Location"] = f"/orders/{new_id}"

    return new_order


@app.get("/orders", response_model=List[OrderRead], tags=["users"])
def list_orders(
        status: Optional[OrderStatus] = Query(None, alias="state"),
        user_id: Optional[int] = Query(None, alias="userId"),
        item_id: Optional[int] = Query(None, alias="itemId"),
        from_: Optional[datetime] = Query(None, alias="from"),
        to_: Optional[datetime] = Query(None, alias="to"),
):
    """
    Query the collection of orders with rich filters.

    Supports:
    - Filter by status (pending/active/returned)
    - Filter by userId
    - Filter by itemId
    - Filter by created_at time range

    Demonstrates correct REST collection filtering practices.
    """

    results = list(orders.values())

    if status is not None:
        results = [o for o in results if o.status == status]
    if user_id is not None:
        results = [o for o in results if o.user_id == user_id]
    if item_id is not None:
        results = [o for o in results if o.item_id == item_id]
    if from_ is not None:
        results = [o for o in results if o.created_at >= from_]
    if to_ is not None:
        results = [o for o in results if o.created_at <= to_]

    return [_ensure_order_links(o) for o in results]


@app.get("/orders/{orderId}", response_model=OrderRead, tags=["users"])
def get_order_by_id(orderId: int = Path(...)):
    """
    Retrieve a single order by ID.
    """
    if orderId not in orders:
        raise HTTPException(404, "Order not found")
    return _ensure_order_links(orders[orderId])


@app.delete("/orders/{orderId}", tags=["users"])
def cancel_order(orderId: int = Path(...)):
    """
    Cancel an order.

    Only orders in PENDING state can be cancelled.
    """

    if orderId not in orders:
        raise HTTPException(404, "Order not found")

    order = orders[orderId]

    if order.status != OrderStatus.PENDING:
        raise HTTPException(400, "Cannot cancel non-pending order")

    old_status = order.status
    order.status = OrderStatus.CANCELLED
    order.updated_at = datetime.now(UTC)

    _create_log(order.id, from_status=old_status, to_status=order.status)

    return {"message": "Order cancelled successfully"}


@app.patch("/orders/{orderId}/status", response_model=OrderRead, tags=["admins"])
def update_order_status(status_update: OrderStatusUpdate, orderId: int = Path(...)):
    """
    Admin-only endpoint to modify order status manually.

    Demonstrates:
    - Controlled state transitions
    - Log creation
    - HATEOAS enforcement
    """

    if orderId not in orders:
        raise HTTPException(404, "Order not found")

    order = orders[orderId]
    old_status = order.status
    new_status = status_update.new_status

    # Terminal states cannot be modified
    if old_status in [OrderStatus.CANCELLED, OrderStatus.RETURNED]:
        raise HTTPException(
            400,
            f"Cannot update terminal state '{old_status.value}'",
        )

    # Only log if there's a real state change
    if old_status != new_status:
        order.status = new_status
        order.updated_at = datetime.now(UTC)
        _create_log(order.id, from_status=old_status, to_status=new_status)

    return _ensure_order_links(order)


@app.get("/orders/{orderId}/logs", response_model=List[OrderLogRead], tags=["admins"])
def get_order_logs(orderId: int = Path(...)):
    """
    Retrieve the audit trail of state transitions for an order.
    """
    if orderId not in orders:
        raise HTTPException(404, "Order not found")
    return order_logs.get(orderId, [])


@app.post("/orders/{orderId}/confirm", tags=["users"])
def confirm_order(
        orderId: int = Path(...),
        background_tasks: BackgroundTasks = None,
        response: Response = None,
):
    """
    Begin async confirmation of an order.

    Returns:
    - 202 Accepted
    - Location header → /jobs/{jobId}

    The actual confirmation runs asynchronously.
    """

    if orderId not in orders:
        raise HTTPException(404, "Order not found")

    order = orders[orderId]

    # Only pending orders can be confirmed
    if order.status != OrderStatus.PENDING:
        raise HTTPException(400, "Only pending orders can be confirmed")

    # Create async job metadata
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "jobId": job_id,
        "orderId": orderId,
        "status": "pending",
        "result": None,
    }

    # Run background task
    background_tasks.add_task(_process_confirm_order, orderId, job_id)

    # REST-compliant async response
    response.status_code = 202
    response.headers["Location"] = f"/jobs/{job_id}"

    return {"jobId": job_id, "status": "pending"}


@app.get("/jobs/{jobId}", tags=["jobs"])
def get_job(jobId: str = Path(...), response: Response = None):
    """
    Query the status of an async job.

    Behavior:
    - If job is still pending/running → return 202 + Location header
    - If succeeded → return 200 + result link
    - If failed → return 200 + failure reason
    """

    job = jobs.get(jobId)
    if job is None:
        raise HTTPException(404, "Job not found")

    status = job["status"]

    # Pending/running = async job not complete
    if status in ("pending", "running"):
        response.status_code = 202
        response.headers["Location"] = f"/jobs/{jobId}"

    body = {
        "jobId": job["jobId"],
        "status": status,
    }

    # Attach result if available
    result = job.get("result")
    if isinstance(result, str) and result.startswith("/orders/"):
        body["result"] = {"order": result}
    elif result is not None:
        body["result"] = result

    return body


@app.get("/")
def root():
    """Simple health check / landing route."""
    return {"message": "Order & Rental Service API is running. See /docs for API explorer."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)