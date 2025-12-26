"""
Módulo de Sincronização com Google Drive
=========================================

Este módulo gerencia o backup e sincronização do banco de dados
entre diferentes máquinas usando o Google Drive for Desktop.

Fluxo:
- LOJA (Master): Exporta o banco local para o Google Drive
- GERENTE (Leitura): Baixa a versão mais recente do Google Drive

Autor: Sistema de Estoque
"""

import os
import shutil
from datetime import datetime

# Configurações
CAMINHO_BANCO_LOCAL = 'database/padaria.db'
NOME_ARQUIVO_NUVEM = 'padaria_snapshot.db'


def exportar_para_nuvem(caminho_drive):
    """
    Exporta (copia) o banco de dados local para o Google Drive.
    
    Args:
        caminho_drive (str): Caminho absoluto da pasta do Google Drive
        
    Returns:
        bool: True se exportou com sucesso, False caso contrário
    """
    print("\n" + "="*60)
    print("📤 EXPORTANDO BACKUP PARA NUVEM")
    print("="*60)
    
    # Verifica se o banco local existe
    if not os.path.exists(CAMINHO_BANCO_LOCAL):
        print("⚠️  Banco de dados local não encontrado.")
        print(f"   Caminho: {os.path.abspath(CAMINHO_BANCO_LOCAL)}")
        return False
    
    # Verifica se a pasta do Google Drive existe
    if not os.path.exists(caminho_drive):
        print("❌ ERRO: Pasta do Google Drive não encontrada!")
        print(f"   Caminho: {caminho_drive}")
        print("\n💡 Dicas:")
        print("   - Verifique se o Google Drive está instalado")
        print("   - Confirme se o caminho no arquivo .env está correto")
        print("   - Aguarde a sincronização inicial do Google Drive")
        return False
    
    # Caminho completo do arquivo de destino
    destino = os.path.join(caminho_drive, NOME_ARQUIVO_NUVEM)
    
    try:
        # Copia o arquivo
        print(f"📋 Copiando: {CAMINHO_BANCO_LOCAL}")
        print(f"📂 Destino:  {destino}")
        shutil.copy2(CAMINHO_BANCO_LOCAL, destino)
        
        # Informações sobre o arquivo
        tamanho_mb = os.path.getsize(destino) / (1024 * 1024)
        timestamp = datetime.now().strftime('%d/%m/%Y às %H:%M:%S')
        
        print(f"\n✅ Backup exportado com sucesso!")
        print(f"   Tamanho: {tamanho_mb:.2f} MB")
        print(f"   Data/Hora: {timestamp}")
        print("="*60 + "\n")
        return True
        
    except Exception as e:
        print(f"\n❌ ERRO ao exportar backup: {e}")
        print("="*60 + "\n")
        return False


def sincronizar_do_nuvem(caminho_drive):
    """
    Sincroniza (baixa) o banco de dados do Google Drive se houver versão mais recente.
    
    Args:
        caminho_drive (str): Caminho absoluto da pasta do Google Drive
        
    Returns:
        bool: True se sincronizou ou já estava atualizado, False em caso de erro
    """
    print("\n" + "="*60)
    print("📥 SINCRONIZANDO DO GOOGLE DRIVE")
    print("="*60)
    
    # Caminho completo do arquivo na nuvem
    origem = os.path.join(caminho_drive, NOME_ARQUIVO_NUVEM)
    
    # Verifica se existe backup na nuvem
    if not os.path.exists(origem):
        print("⚠️  Nenhum backup encontrado no Google Drive.")
        print(f"   Caminho: {origem}")
        print("\n💡 Possíveis causas:")
        print("   - O computador da LOJA ainda não exportou nenhum backup")
        print("   - O Google Drive ainda não sincronizou o arquivo")
        print("   - O caminho configurado está incorreto")
        return False
    
    # Verifica se o banco local existe
    banco_local_existe = os.path.exists(CAMINHO_BANCO_LOCAL)
    
    if not banco_local_existe:
        print("ℹ️  Banco de dados local não encontrado. Criando pela primeira vez...")
        decisao = 'baixar'
    else:
        # Compara as datas de modificação
        data_nuvem = os.path.getmtime(origem)
        data_local = os.path.getmtime(CAMINHO_BANCO_LOCAL)
        
        timestamp_nuvem = datetime.fromtimestamp(data_nuvem).strftime('%d/%m/%Y %H:%M:%S')
        timestamp_local = datetime.fromtimestamp(data_local).strftime('%d/%m/%Y %H:%M:%S')
        
        print(f"📅 Versão na Nuvem: {timestamp_nuvem}")
        print(f"📅 Versão Local:    {timestamp_local}")
        
        if data_nuvem > data_local:
            print("\n🆕 Nova versão disponível na nuvem!")
            decisao = 'baixar'
        else:
            print("\n✅ Seu sistema já está atualizado.")
            print("="*60 + "\n")
            return True
    
    # Baixar/substituir o arquivo local
    if decisao == 'baixar':
        try:
            # Cria a pasta database se não existir
            os.makedirs(os.path.dirname(CAMINHO_BANCO_LOCAL), exist_ok=True)
            
            print(f"\n📥 Baixando: {origem}")
            print(f"📂 Destino:  {os.path.abspath(CAMINHO_BANCO_LOCAL)}")
            shutil.copy2(origem, CAMINHO_BANCO_LOCAL)
            
            tamanho_mb = os.path.getsize(CAMINHO_BANCO_LOCAL) / (1024 * 1024)
            print(f"\n✅ Banco de dados atualizado com sucesso!")
            print(f"   Tamanho: {tamanho_mb:.2f} MB")
            print("="*60 + "\n")
            return True
            
        except Exception as e:
            print(f"\n❌ ERRO ao sincronizar: {e}")
            print("="*60 + "\n")
            return False
