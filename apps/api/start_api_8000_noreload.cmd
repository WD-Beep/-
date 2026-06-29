@echo off
cd /d "%~dp0"
echo [api] Starting uvicorn on http://127.0.0.1:8000 ...
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> api.codex.8000.noreload.log 2>> api.codex.8000.noreload.err.log
