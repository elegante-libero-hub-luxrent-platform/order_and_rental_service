from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Enumeration of job processing states."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobBase(BaseModel):
    """Base model for shared job fields."""
    order_id: int = Field(..., description="ID of the related order.", example=101)


class JobCreate(JobBase):
    """
    Payload for creating a new job record.
    Usually internal-only (your code creates jobs, not users).
    """
    status: JobStatus = Field(..., description="Initial job status.", example="pending")


class JobRead(JobBase):
    """
    Full job representation returned by the API.
    Matches the `jobs` table in Cloud SQL.
    """
    job_id: str = Field(..., description="Unique job identifier (UUID).", example="c59df4b8-e9ad-4b2d-a3ad-4cebe21865a5")
    status: JobStatus = Field(..., description="Current job status.", example="running")
    result: Optional[str] = Field(
        default=None,
        description="Job result. If succeeded, contains a URL. If failed, contains error details.",
        example="/orders/101"
    )
    # In DB schema, timestamp is not auto-stored.
    # If you later add a timestamp column, you can add it here.


    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "c59df4b8-e9ad-4b2d-a3ad-4cebe21865a5",
                    "order_id": 101,
                    "status": "succeeded",
                    "result": "/orders/101"
                }
            ]
        }
    }
