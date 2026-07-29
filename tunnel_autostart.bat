@echo off
:loop
echo Starting localtunnel...
npx -y localtunnel --port 8800 --subdomain astraquote-evolnex
echo Tunnel dropped. Restarting in 3 seconds...
timeout /t 3 /nobreak
goto loop
