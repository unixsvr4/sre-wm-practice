#!/bin/bash
# Generate steady traffic against the weedmaps demo app so golden signals appear in Grafana
BASE="${1:-http://localhost:8080}"
echo "Sending traffic to $BASE — Ctrl+C to stop"
echo "Watch dashboards at http://localhost:3000"
while true; do
    curl -sf "$BASE/api/products"                           > /dev/null
    curl -sf "$BASE/api/products/$((RANDOM % 150))"        > /dev/null  # ~33% 404s
    curl -sf "$BASE/api/orders"                             > /dev/null
    curl -sf -X POST "$BASE/api/orders" -H "Content-Type: application/json" -d '{}' > /dev/null
    sleep 0.3
done
