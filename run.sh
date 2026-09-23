#!/usr/bin/env bash
echo "Backend (from this repository, with the venv active):"
echo "  python -m uvicorn back.main:app --host 127.0.0.1 --port 8000 --reload"
echo "API documentation: http://127.0.0.1:8000/docs"
echo "Run the ML teammate's worker separately, watching the same tickets directory."
echo "Frontend uses POST /api/tickets and polls GET /api/tickets/{id}."
