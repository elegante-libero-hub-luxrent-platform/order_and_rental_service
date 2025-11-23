#!/bin/bash

BASE=${1:-http://localhost:8000}

echo "[STEP 1] Create order"
CREATE=$(curl -s -i -X POST "$BASE/orders" \
    -H "Content-Type: application/json" \
    -d '{"user_id":3,"item_id":10,"start_date":"2025-01-01","end_date":"2025-01-05"}')

echo "$CREATE"

ORDER_ID=$(echo "$CREATE" \
  | tr -d '\r' \
  | grep -i '^location:' \
  | sed 's/.*\/orders\///')

echo "Order ID = $ORDER_ID"

if [ -z "$ORDER_ID" ]; then
  echo "[ERROR] Failed to parse Order ID from Location header"
  exit 1
fi

echo
echo "[STEP 2] First confirm (should succeed, 202 Accepted)"
FIRST_CONFIRM=$(curl -s -i -X POST "$BASE/orders/$ORDER_ID/confirm")
echo "$FIRST_CONFIRM"

echo
echo "[INFO] Wait a bit for background job..."
sleep 1

echo
echo "[STEP 3] Second confirm (should return 400 Bad Request)"
SECOND_CONFIRM=$(curl -s -i -X POST "$BASE/orders/$ORDER_ID/confirm")
echo "$SECOND_CONFIRM"

STATUS_LINE=$(echo "$SECOND_CONFIRM" | head -n 1)

if [[ "$STATUS_LINE" == *"400"* ]]; then
  echo "Expected 400 on second confirm (failed case) – PASS"
else
  echo "Expected 400 on second confirm, got: $STATUS_LINE"
  exit 1
fi
