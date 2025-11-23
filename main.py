from __future__ import annotations

import os
import uuid
from datetime import datetime, UTC
from typing import Dict, List, Optional

import mysql.connector
from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query, Response
from google.cloud import secretmanager

from models.order import (
    OrderCreate,
    OrderRead,
    OrderStatus,
    OrderStatusUpdate,
)
from models.log import OrderLogRead
from models.job import JobRead, JobStatus

# ---------------------------------------------------------------------
# Server Port Configuration (Cloud Run / local development)
# ---------------------------------------------------------------------
port = int(os.environ.get("PORT", os.environ.get("FASTAPIPORT", 8000)))

# ---------------------------------------------------------------------
# Secret Manager helper for retrieving MySQL password
# ---------------------------------------------------------------------
def get_secret(secret_name: str) -> str:
    """
    Fetch secrets (e.g., DB password) from Google Secret Manager.
    """
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{os.environ['GCP_PROJECT_ID']}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


# ---------------------------------------------------------------------
# Database Configuration (Cloud SQL)
# ---------------------------------------------------------------------
DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ["DB_USER"]
DB_NAME = os.environ["DB_NAME"]
DB_PASSWORD = get_secret("orders-db-password")

# In-memory cache only for tracking real-time job status during background execution.
# The true persistent job state is stored in Cloud SQL.
jobs_memory: Dict[str, Dict] = {}


def get_connection():
    """
    Create a new MySQL connection.
    """
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
    )


# ---------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------
app = FastAPI(
    title="Order & Rental Service API",
    description="Handles order lifecycle, state transitions, async jobs, and logging.",
    version="1.0.0",
)

# ---------------------------------------------------------------------
# Helper Functions for HATEOAS + Mapping DB Rows to Pydantic Models
# ---------------------------------------------------------------------
def _build_order_links(order: OrderRead) -> Dict[str, str]:
    """
    Construct HATEOAS links for an order resource.
    """
    return {
        "self": f"/orders/{order.id}",
        "user": f"/users/{order.user_id}",
        "item": f"/items/{order.item_id}",
    }


def _ensure_order_links(order: OrderRead) -> OrderRead:
    """
    Attach HATEOAS links to the OrderRead object if missing.
    """
    if getattr(order, "links", None) is None:
        order.links = _build_order_links(order)
    return order


def _row_to_order(row) -> OrderRead:
    """
    Convert a database row into an OrderRead model.
    Expected row layout follows schema.sql:
    (id, user_id, item_id, status, total_rent, deposit,
     created_at, updated_at, start_date, end_date)
    """
    return _ensure_order_links(
        OrderRead(
            id=row[0],
            user_id=row[1],
            item_id=row[2],
            status=OrderStatus(row[3]),
            total_rent=row[4],
            deposit=row[5],
            created_at=row[6],
            updated_at=row[7],
            start_date=row[8],
            end_date=row[9],
        )
    )


def _row_to_log(row) -> OrderLogRead:
    """
    Convert a DB row into an OrderLogRead object.
    """
    from_status = OrderStatus(row[2]) if row[2] is not None else None
    to_status = OrderStatus(row[3]) if row[3] is not None else None
    return OrderLogRead(
        log_id=row[0],
        order_id=row[1],
        from_status=from_status,
        to_status=to_status,
        timestamp=row[4],
    )


def _create_log_db(conn, order_id: int, from_status: OrderStatus, to_status: OrderStatus, ts: Optional[datetime] = None):
    """
    Insert a new order status transition log into the database.
    """
    if ts is None:
        ts = datetime.now(UTC)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO order_logs (order_id, from_status, to_status, timestamp)
        VALUES (%s, %s, %s, %s)
        """,
        (order_id, from_status.value, to_status.value, ts),
    )
    conn.commit()
    cursor.close()


# ---------------------------------------------------------------------
# Background Task: Asynchronous Order Confirmation
# ---------------------------------------------------------------------
def _process_confirm_order(order_id: int, job_id: str) -> None:
    """
    Background task simulating async confirmation workflow.
    Updates both:
    - jobs_memory: real-time tracking for the background process
    - jobs table: persistent status for API querying
    """
    jobs_memory[job_id]["status"] = JobStatus.RUNNING.value

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, item_id, status, total_rent, deposit,
                   created_at, updated_at, start_date, end_date
            FROM orders
            WHERE id = %s
            """,
            (order_id,),
        )
        row = cursor.fetchone()

        if row is None:
            # Order not found → mark job as failed
            cursor.execute(
                "UPDATE jobs SET status=%s, result=%s WHERE job_id=%s",
                (JobStatus.FAILED.value, "order_not_found", job_id),
            )
            conn.commit()
            cursor.close()
            conn.close()

            jobs_memory[job_id]["status"] = JobStatus.FAILED.value
            jobs_memory[job_id]["result"] = "order_not_found"
            return

        current_status = OrderStatus(row[3])
        if current_status != OrderStatus.PENDING:
            # Invalid state transition
            cursor.execute(
                "UPDATE jobs SET status=%s, result=%s WHERE job_id=%s",
                (JobStatus.FAILED.value, "invalid_state", job_id),
            )
            conn.commit()
            cursor.close()
            conn.close()

            jobs_memory[job_id]["status"] = JobStatus.FAILED.value
            jobs_memory[job_id]["result"] = "invalid_state"
            return

        # Apply confirmation → update status to ACTIVE
        now = datetime.now(UTC)
        cursor.execute(
            """
            UPDATE orders
            SET status=%s, updated_at=%s
            WHERE id=%s
            """,
            (OrderStatus.ACTIVE.value, now, order_id),
        )
        _create_log_db(conn, order_id, current_status, OrderStatus.ACTIVE, now)

        # Mark job as succeeded
        cursor.execute(
            "UPDATE jobs SET status=%s, result=%s WHERE job_id=%s",
            (JobStatus.SUCCEEDED.value, f"/orders/{order_id}", job_id),
        )
        conn.commit()
        cursor.close()
        conn.close()

        jobs_memory[job_id]["status"] = JobStatus.SUCCEEDED.value
        jobs_memory[job_id]["result"] = f"/orders/{order_id}"

    except Exception:
        # Catch-all fallback: record failure in DB and memory
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE jobs SET status=%s, result=%s WHERE job_id=%s",
                (JobStatus.FAILED.value, "internal_error", job_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception:
            pass

        jobs_memory[job_id]["status"] = JobStatus.FAILED.value
        jobs_memory[job_id]["result"] = "internal_error"


# ---------------------------------------------------------------------
# ORDERS API
# ---------------------------------------------------------------------
@app.post("/orders", response_model=OrderRead, status_code=201, tags=["users"])
def create_order(order: OrderCreate, response: Response):
    """
    Create a new order and persist it to Cloud SQL.
    Automatically:
    - sets initial status to PENDING
    - generates a PENDING→PENDING log entry
    - returns Location header for REST compliance
    """
    now = datetime.now(UTC)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO orders (
            user_id, item_id, status, total_rent, deposit,
            created_at, updated_at, start_date, end_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            order.user_id,
            order.item_id,
            OrderStatus.PENDING.value,
            499.99,      # business logic placeholder
            1000.00,     # business logic placeholder
            now,
            now,
            order.start_date,
            order.end_date,
        ),
    )
    order_id = cursor.lastrowid

    # Initial log: PENDING -> PENDING
    _create_log_db(conn, order_id, OrderStatus.PENDING, OrderStatus.PENDING, now)

    cursor.execute(
        """
        SELECT id, user_id, item_id, status, total_rent, deposit,
               created_at, updated_at, start_date, end_date
        FROM orders
        WHERE id = %s
        """,
        (order_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        raise HTTPException(500, "Failed to create order")

    order_obj = _row_to_order(row)
    response.headers["Location"] = f"/orders/{order_id}"
    return order_obj


@app.get("/orders", response_model=List[OrderRead], tags=["users"])
def list_orders(
    status: Optional[OrderStatus] = Query(None, alias="state"),
    user_id: Optional[int] = Query(None, alias="userId"),
    item_id: Optional[int] = Query(None, alias="itemId"),
    from_: Optional[datetime] = Query(None, alias="from"),
    to_: Optional[datetime] = Query(None, alias="to"),
):
    """
    List orders with optional filtering:
    - state
    - userId
    - itemId
    - created_at date range
    """
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT id, user_id, item_id, status, total_rent, deposit,
               created_at, updated_at, start_date, end_date
        FROM orders
        WHERE 1=1
    """
    params: List = []

    if status is not None:
        query += " AND status = %s"
        params.append(status.value)
    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)
    if item_id is not None:
        query += " AND item_id = %s"
        params.append(item_id)
    if from_ is not None:
        query += " AND created_at >= %s"
        params.append(from_)
    if to_ is not None:
        query += " AND created_at <= %s"
        params.append(to_)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [_row_to_order(r) for r in rows]


@app.get("/orders/{orderId}", response_model=OrderRead, tags=["users"])
def get_order_by_id(orderId: int = Path(...)):
    """
    Retrieve a single order by ID.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, item_id, status, total_rent, deposit,
               created_at, updated_at, start_date, end_date
        FROM orders
        WHERE id = %s
        """,
        (orderId,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        raise HTTPException(404, "Order not found")

    return _row_to_order(row)


@app.delete("/orders/{orderId}", tags=["users"])
def cancel_order(orderId: int = Path(...)):
    """
    Cancel an order.
    Only orders in PENDING state may be cancelled.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, item_id, status, total_rent, deposit,
               created_at, updated_at, start_date, end_date
        FROM orders
        WHERE id = %s
        """,
        (orderId,),
    )
    row = cursor.fetchone()

    if row is None:
        cursor.close()
        conn.close()
        raise HTTPException(404, "Order not found")

    current_status = OrderStatus(row[3])
    if current_status != OrderStatus.PENDING:
        cursor.close()
        conn.close()
        raise HTTPException(400, "Cannot cancel non-pending order")

    now = datetime.now(UTC)
    cursor.execute(
        """
        UPDATE orders
        SET status=%s, updated_at=%s
        WHERE id=%s
        """,
        (OrderStatus.CANCELLED.value, now, orderId),
    )
    _create_log_db(conn, orderId, current_status, OrderStatus.CANCELLED, now)
    conn.commit()
    cursor.close()
    conn.close()

    return {"message": "Order cancelled successfully"}


@app.patch("/orders/{orderId}/status", response_model=OrderRead, tags=["admins"])
def update_order_status(status_update: OrderStatusUpdate, orderId: int = Path(...)):
    """
    Admin endpoint to change an order's status.
    Restrictions:
      - CANCELLED or RETURNED states are terminal.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, item_id, status, total_rent, deposit,
               created_at, updated_at, start_date, end_date
        FROM orders
        WHERE id = %s
        """,
        (orderId,),
    )
    row = cursor.fetchone()

    if row is None:
        cursor.close()
        conn.close()
        raise HTTPException(404, "Order not found")

    old_status = OrderStatus(row[3])
    new_status = status_update.new_status

    if old_status in [OrderStatus.CANCELLED, OrderStatus.RETURNED]:
        cursor.close()
        conn.close()
        raise HTTPException(400, f"Cannot update terminal state '{old_status.value}'")

    if old_status != new_status:
        now = datetime.now(UTC)
        cursor.execute(
            """
            UPDATE orders
            SET status=%s, updated_at=%s
            WHERE id=%s
            """,
            (new_status.value, now, orderId),
        )
        _create_log_db(conn, orderId, old_status, new_status, now)
        conn.commit()

    # Fetch updated order
    cursor.execute(
        """
        SELECT id, user_id, item_id, status, total_rent, deposit,
               created_at, updated_at, start_date, end_date
        FROM orders
        WHERE id = %s
        """,
        (orderId,),
    )
    row2 = cursor.fetchone()
    cursor.close()
    conn.close()

    return _row_to_order(row2)


@app.get("/orders/{orderId}/logs", response_model=List[OrderLogRead], tags=["admins"])
def get_order_logs(orderId: int = Path(...)):
    """
    Retrieve all status transition logs belonging to a specific order.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT log_id, order_id, from_status, to_status, timestamp
        FROM order_logs
        WHERE order_id = %s
        ORDER BY timestamp ASC, log_id ASC
        """,
        (orderId,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [_row_to_log(r) for r in rows]


# ---------------------------------------------------------------------
# ASYNC CONFIRMATION + JOBS API
# ---------------------------------------------------------------------
@app.post("/orders/{orderId}/confirm", tags=["users"])
def confirm_order(
    orderId: int = Path(...),
    background_tasks: BackgroundTasks = None,
    response: Response = None,
):
    """
    Start an asynchronous confirmation workflow.
    Returns:
      - 202 Accepted
      - Location header → /jobs/{jobId}
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, status
        FROM orders
        WHERE id = %s
        """,
        (orderId,),
    )
    row = cursor.fetchone()

    if row is None:
        cursor.close()
        conn.close()
        raise HTTPException(404, "Order not found")

    current_status = OrderStatus(row[1])
    if current_status != OrderStatus.PENDING:
        cursor.close()
        conn.close()
        raise HTTPException(400, "Only pending orders can be confirmed")

    # Create a job entry in DB
    job_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO jobs (job_id, order_id, status, result)
        VALUES (%s, %s, %s, %s)
        """,
        (job_id, orderId, JobStatus.PENDING.value, None),
    )
    conn.commit()
    cursor.close()
    conn.close()

    # Mirror job in memory for real-time tracking
    jobs_memory[job_id] = {
        "jobId": job_id,
        "orderId": orderId,
        "status": JobStatus.PENDING.value,
        "result": None,
    }

    # Trigger async processing
    background_tasks.add_task(_process_confirm_order, orderId, job_id)

    response.status_code = 202
    response.headers["Location"] = f"/jobs/{job_id}"
    return {"jobId": job_id, "status": JobStatus.PENDING.value}


@app.get("/jobs/{jobId}", response_model=JobRead, tags=["jobs"])
def get_job(jobId: str = Path(...), response: Response = None):
    """
    Query job status.
    If job is not completed:
      - Return HTTP 202 with Location header (polling pattern)
    If completed:
      - Return HTTP 200 with final status + result
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT job_id, order_id, status, result
        FROM jobs
        WHERE job_id = %s
        """,
        (jobId,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        raise HTTPException(404, "Job not found")

    status = JobStatus(row[2])

    # Pending or running → keep returning 202
    if status in (JobStatus.PENDING, JobStatus.RUNNING):
        response.status_code = 202
        response.headers["Location"] = f"/jobs/{jobId}"

    return JobRead(
        job_id=row[0],
        order_id=row[1],
        status=status,
        result=row[3],
    )

# ---------------------------------------------------------------------
# Root Endpoint & __main__
# ---------------------------------------------------------------------
@app.get("/")
def root():
    """
    Health check endpoint.
    """
    return {"message": "Order & Rental Service API is running. See /docs for API explorer."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
