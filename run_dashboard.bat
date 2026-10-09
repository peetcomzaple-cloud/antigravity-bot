@echo off
title Google Antigravity Cloud - Autonomous Fleet Local IDE
cd /d "%~dp0"
echo ===================================================
echo  Starting Google Antigravity Autonomous Fleet...
echo  Local Dashboard: http://127.0.0.1:8501
echo  Security: Bound strictly to localhost (127.0.0.1)
echo  Authentication: Token configured via .env
echo ===================================================
python -m streamlit run dashboard.py --server.port 8501  --theme.base dark
pause
