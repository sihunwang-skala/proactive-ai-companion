#!/bin/sh
cd "$(dirname "$0")" && exec python3 -m uvicorn app.main:get_app --factory --host 127.0.0.1 --port "${PORT:-8787}"
