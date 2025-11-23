#!/bin/bash

BASE="http://localhost:8000"

echo "[FILTER by userId]"
curl "$BASE/orders?userId=1"
echo -e "\n"

echo "[FILTER by state]"
curl "$BASE/orders?state=active"
echo -e "\n"

echo "[FILTER by itemId]"
curl "$BASE/orders?itemId=10"
echo -e "\n"