#!/bin/bash

BASE=${1:-http://localhost:8000}

echo "[TEST] Create order -> expect 201 Created"

curl -i -X POST "$BASE/orders" \
    -H "Content-Type: application/json" \
    -d '{
        "user_id": 1,
        "item_id": 5,
        "start_date": "2025-01-01",
        "end_date": "2025-01-05"
    }'
