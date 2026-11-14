@echo off
REM ===========================================================================
REM  Comparador de Passagens Rodoviarias - inicializacao (Windows)
REM  Abre os 4 servicos e o agregador, cada um em sua propria janela.
REM  Uso: de dois cliques em start.bat ou execute "start.bat" no prompt.
REM ===========================================================================
chcp 65001 > nul
cd /d "%~dp0"

set PY=python
where python > /dev/null 2> nul
if errorlevel 1 (
    where py > /dev/null 2> nul
    if errorlevel 1 (
        echo ERRO: Python nao encontrado. Instale o Python 3 e marque "Add to PATH".
        pause
        exit /b 1
    )
    set PY=py
)

echo ==============================================================
echo   Iniciando o Comparador de Passagens Rodoviarias
echo ==============================================================

start "Servico 1 - Viacao Maraba (5001)"  cmd /k %PY% servicos\servico_1_viacao_maraba.py
start "Servico 2 - TransBrasil (5002)"    cmd /k %PY% servicos\servico_2_transbrasil.py
start "Servico 3 - Expresso Para (5003)"  cmd /k %PY% servicos\servico_3_expresso_para.py
start "Servico 4 - Rodoviaria Sul (5004)" cmd /k %PY% servicos\servico_4_rodoviaria_sul.py

echo Aguardando os servicos subirem...
timeout /t 2 /nobreak > nul

start "Agregador (6000)" cmd /k %PY% agregador\agregador.py

echo.
echo Servicos (5001-5004) e agregador (6000) iniciados em janelas separadas.
echo Agora rode o cliente neste terminal:
echo     %PY% cliente\cliente.py
echo Ou os experimentos:
echo     %PY% experimentos\experimento.py --latencia 0.8
