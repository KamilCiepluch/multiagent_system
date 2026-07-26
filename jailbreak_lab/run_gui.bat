@echo off
REM Launcher GUI (Gradio) na srodowisku conda `system_agentowy2` (Windows).
REM Otworzy http://127.0.0.1:7860 w przegladarce. Ta sama baza co REPL (jailbreaks.db).
"C:\Users\kamil\.conda\envs\system_agentowy2\python.exe" "%~dp0gui.py" %*
