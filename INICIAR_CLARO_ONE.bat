@echo off
setlocal
cd /d "%~dp0"
title Claro One

if not exist ".venv\Scripts\python.exe" (
  echo ERRO: o projeto ainda nao foi instalado.
  echo Execute INSTALAR.bat primeiro.
  pause
  exit /b 1
)

if not exist ".env" (
  echo ERRO: o arquivo .env nao existe. Execute INSTALAR.bat primeiro.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -c "from config import settings; import sys; k=settings.groq_api_key.strip().lower(); sys.exit(0 if k and not k.startswith(('sua_', 'seu_', 'cole_', 'your_', 'gsk_xxx')) else 1)"
if errorlevel 1 (
  echo ERRO: configure GROQ_API_KEY no arquivo .env.
  echo Obtenha a chave em https://console.groq.com/keys
  pause
  exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo ERRO: a porta 8000 ja esta em uso. Feche a outra instancia e tente novamente.
  pause
  exit /b 1
)

echo Iniciando o Claro One em http://127.0.0.1:8000
echo Para encerrar, pressione Ctrl+C.
start "" powershell -NoProfile -WindowStyle Hidden -Command "$limit=(Get-Date).AddSeconds(30); do { try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 1; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8000'; exit } } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $limit)"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000

echo.
echo Servidor encerrado.
pause
exit /b 0
