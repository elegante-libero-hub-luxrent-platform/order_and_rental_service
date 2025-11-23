#!/bin/bash

# Default base URL is local Uvicorn, can override by passing as first arg
BASE=${1:-http://localhost:8000}

echo "[STEP 1] Create order"
CREATE=$(curl -s -i -X POST "$BASE/orders" \
    -H "Content-Type: application/json" \
    -d '{"user_id": 2, "item_id": 99, "start_date": "2025-01-01", "end_date": "2025-01-05"}')

echo "$CREATE"

# Extract Location header line (case-insensitive)
ORDER_LOCATION_LINE=$(echo "$CREATE" | grep -i '^location:')
# e.g. "location: /orders/101"

# Take the second column (the path), then strip \r
ORDER_PATH=$(echo "$ORDER_LOCATION_LINE" | awk '{print $2}' | tr -d '\r')

# Extract the numeric id after the last slash
ORDER_ID=${ORDER_PATH##*/}

echo "Order ID = $ORDER_ID"

echo
echo "[STEP 2] Confirm order (async)"
CONFIRM=$(curl -s -i -X POST "$BASE/orders/$ORDER_ID/confirm")
echo "$CONFIRM"

JOB_LOCATION_LINE=$(echo "$CONFIRM" | grep -i '^location:')
JOB_PATH=$(echo "$JOB_LOCATION_LINE" | awk '{print $2}' | tr -d '\r')
JOB_ID=${JOB_PATH##*/}

echo "Job ID = $JOB_ID"

echo
echo "[STEP 3] Start polling job"
for i in {1..5}
do
  echo "Polling #$i"
  RES=$(curl -s "$BASE/jobs/$JOB_ID")
  echo "$RES"
  if [[ "$RES" == *"\"status\":\"succeeded\""* ]]; then
    echo "Job completed successfully"
    exit 0
  fi
  sleep 1
done

echo "Job did NOT complete"
exit 1
