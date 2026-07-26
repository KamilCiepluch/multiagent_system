@echo off
REM Launcher REPL na środowisku conda `system_agentowy2` (Windows).
REM Argumenty przechodzą 1:1 do lab.py, np.:  run.bat --model qwen3.6:27b-ctx8k --session dan
"C:\Users\kamil\.conda\envs\system_agentowy2\python.exe" "%~dp0lab.py" %*
