@echo off
title INSTALADOR DO SISTEMA DE ESTOQUE
color 0B
cls

echo ========================================================
echo      INSTALACAO INICIAL - SISTEMA DE PADARIA
echo ========================================================
echo.
echo Verificando se o Python ja esta instalado...

python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python ja encontrado!
    goto :instalar_libs
)

echo [AVISO] Python nao encontrado.
echo Iniciando instalacao automatica do Python...
echo Por favor, aguarde e permita permissao de Administrador se solicitado.
echo Isso pode levar alguns minutos...
echo.

:: O comando abaixo instala o Python de forma passiva e MARCA O ADD TO PATH SOZINHO
:: /passive = Mostra barra de progresso mas não pede cliques
:: PrependPath=1 = Adiciona ao PATH (Crucial para funcionar)
start /wait instaladores/python_setup.exe /passive PrependPath=1 Include_test=0

echo.
echo Verificando instalacao...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Nao foi possivel instalar o Python automaticamente.
    echo Tente rodar o arquivo 'python_setup.exe' dentro da pasta 'instaladores' manualmente.
    echo Lembre-se de marcar a opcao "Add Python to PATH".
    pause
    exit
)
echo [SUCESSO] Python instalado!

:instalar_libs
echo.
echo ========================================================
echo      INSTALANDO BIBLIOTECAS DO SISTEMA
echo ========================================================
echo.
echo Instalando Flask, OpenPyXL e dependencias...
echo.

pip install -r requirements.txt

echo.
echo ========================================================
echo      CRIANDO BANCO DE DADOS
echo ========================================================
echo.
echo Executando script de criacao do banco...
python database\setup_db_v2.py

echo.
echo ========================================================
echo      INSTALACAO CONCLUIDA COM SUCESSO!
echo ========================================================
echo.
echo Agora voce pode usar o icone "INICIAR_SISTEMA" para abrir o programa.
echo.
pause