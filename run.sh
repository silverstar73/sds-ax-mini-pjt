#!/usr/bin/env bash
# 실행: ./run.sh          -> CLI 데모 1회 질의
#      ./run.sh api       -> POST /query API 서버 (uvicorn)
set -e
cd "$(dirname "$0")/src"

if [ "$1" = "api" ]; then
  exec uvicorn api:api --reload --port 8000
else
  exec python agent.py
fi
