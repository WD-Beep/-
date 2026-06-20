@echo off
cd /d "%~dp0"
echo [api] Installing/updating dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo [api] pip install failed. Use: python -m pip install -r requirements.txt
  exit /b 1
)
echo [api] Starting uvicorn on http://127.0.0.1:8000 ...
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload >> api.codex.8000.reload.log 2>> api.codex.8000.reload.err.log
