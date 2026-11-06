#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --build api airflow
if [ "$#" -eq 0 ]; then
  docker compose exec -T -w /opt/semo api python daily_collect.py \
    --programs-only --program-sources do,udream --direct-program-fetch \
    --output /opt/airflow/semo-data
else
  docker compose cp "$1" api:/tmp/semo-programs-import.json
  docker compose exec -T -w /opt/semo api python daily_collect.py \
    --import-json /tmp/semo-programs-import.json --output /opt/airflow/semo-data
fi
docker compose exec -T -w /opt/semo api python -m semo.index_cli
docker compose exec -T -w /opt/semo api python -m semo.index_cli --status
