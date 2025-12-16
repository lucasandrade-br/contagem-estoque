@echo off
title SISTEMA DE ESTOQUE - PADARIA
color 0A

echo Iniciando o sistema...
echo Por favor, nao feche esta janela preta enquanto usar o sistema.
echo.

:: Verifica se o Python esta instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERRO: Python nao encontrado!
    echo Instale o Python e marque a opcao "Add Python to PATH".
    pause
    exit
)

:: Inicia o Launcher Python
python launcher.py

pause