import os
import sys
import shutil
import socket
import webbrowser
import time
import atexit
from datetime import datetime
from threading import Timer
from dotenv import load_dotenv
from app import create_app  # Importa a factory
from config import Config
from app.sync_drive import exportar_para_nuvem, sincronizar_do_nuvem

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

def fazer_backup():
    """Cria uma cópia de segurança do banco de dados antes de iniciar."""
    db_file = 'database\padaria.db'
    backup_dir = 'backups'
    
    if not os.path.exists(db_file):
        print("⚠️  Banco de dados não encontrado. Será criado ao iniciar.")
        return

    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    # Nome do arquivo com data/hora: padaria_2025-12-08_18-00.db
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
    backup_file = os.path.join(backup_dir, f"padaria_{timestamp}.db")
    
    try:
        shutil.copy2(db_file, backup_file)
        print(f"✅ Backup realizado com sucesso: {backup_file}")
        
        # Limpeza: Mantém apenas os últimos 5 backups para não lotar o disco
        backups = sorted(os.listdir(backup_dir))
        while len(backups) > 5:
            arquivo_removido = os.path.join(backup_dir, backups.pop(0))
            os.remove(arquivo_removido)
            print(f"🗑️  Backup antigo removido: {os.path.basename(arquivo_removido)}")
            
    except Exception as e:
        print(f"❌ Erro ao fazer backup: {e}")

def obter_ip_local():
    """Descobre o IP real da máquina na rede Wi-Fi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Não precisa conectar de verdade, só simula para pegar a interface correta
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def abrir_navegador(url):
    """Abre o navegador automaticamente após 1.5 segundos."""
    webbrowser.open(url)

def validar_configuracao():
    """Valida as configurações do arquivo .env antes de iniciar o sistema."""
    print("\n" + "="*60)
    print("🔍 VALIDANDO CONFIGURAÇÕES")
    print("="*60)
    
    perfil = os.getenv('PERFIL_MAQUINA', '').strip().upper()
    caminho_drive = os.getenv('CAMINHO_GOOGLE_DRIVE', '').strip()
    
    # Validação 1: PERFIL_MAQUINA deve estar preenchido
    if not perfil:
        print("❌ ERRO: Variável PERFIL_MAQUINA não foi configurada!")
        print("\n📋 INSTRUÇÕES:")
        print("   1. Abra o arquivo .env na pasta raiz do projeto")
        print("   2. Defina PERFIL_MAQUINA=LOJA ou PERFIL_MAQUINA=GERENTE")
        print("   3. Salve o arquivo e execute novamente")
        print("\n" + "="*60)
        sys.exit(1)
    
    # Validação 2: PERFIL_MAQUINA deve ser LOJA ou GERENTE
    if perfil not in ['LOJA', 'GERENTE']:
        print(f"❌ ERRO: Perfil '{perfil}' é inválido!")
        print("\n✅ Valores permitidos:")
        print("   - LOJA (exporta backups para o Google Drive)")
        print("   - GERENTE (sincroniza/baixa do Google Drive)")
        print("\n" + "="*60)
        sys.exit(1)
    
    # Validação 3: CAMINHO_GOOGLE_DRIVE deve estar preenchido
    if not caminho_drive:
        print("❌ ERRO: Variável CAMINHO_GOOGLE_DRIVE não foi configurada!")
        print("\n📋 INSTRUÇÕES:")
        print("   1. Abra o arquivo .env na pasta raiz do projeto")
        print("   2. Defina o caminho completo da pasta do Google Drive")
        print("   3. Exemplo: CAMINHO_GOOGLE_DRIVE=C:/Users/SeuUsuario/Google Drive/Backups")
        print("\n💡 DICA: Use barras normais (/) em vez de barras invertidas (\\)")
        print("="*60)
        sys.exit(1)
    
    # Validação 4: Caminho do Google Drive deve existir
    if not os.path.exists(caminho_drive):
        print(f"⚠️  AVISO: Caminho do Google Drive não encontrado!")
        print(f"   Caminho: {caminho_drive}")
        print("\n💡 Possíveis causas:")
        print("   - Google Drive for Desktop não está instalado")
        print("   - Google Drive ainda não sincronizou a pasta")
        print("   - Caminho digitado incorretamente no arquivo .env")
        print("\n📋 INSTRUÇÕES:")
        print("   1. Instale o Google Drive for Desktop")
        print("   2. Aguarde a sincronização inicial")
        print("   3. Crie a pasta de backups no Google Drive")
        print("   4. Corrija o caminho no arquivo .env")
        print("\n" + "="*60)
        sys.exit(1)
    
    print(f"✅ Perfil configurado: {perfil}")
    print(f"✅ Google Drive: {caminho_drive}")
    print("="*60 + "\n")
    
    return perfil, caminho_drive

if __name__ == "__main__":
    print("="*60)
    print("🥐 SISTEMA DE ESTOQUE - INICIANDO")
    print("="*60)

    # 1. Valida configurações do .env
    PERFIL, CAMINHO_DRIVE = validar_configuracao()

    # 2. Executa backup local
    fazer_backup()

    # 3. Sincronização com Google Drive
    if PERFIL == 'LOJA':
        # Computador da LOJA: Exporta para a nuvem ao iniciar
        exportar_para_nuvem(CAMINHO_DRIVE)
        
        # Registra função para exportar novamente ao fechar o sistema
        atexit.register(lambda: exportar_para_nuvem(CAMINHO_DRIVE))
        print("💾 Backup automático configurado para ao fechar o sistema.\n")
        
    elif PERFIL == 'GERENTE':
        # Computador do GERENTE: Sincroniza (baixa) da nuvem
        sincronizar_do_nuvem(CAMINHO_DRIVE)

    # 4. Descobre IP para os Tablets
    ip = obter_ip_local()
    port = 5000
    url = f"http://{ip}:{port}"

    print("\n" + "*"*60)
    print(f"🚀 SISTEMA ONLINE! (Perfil: {PERFIL})")
    print(f"💻 No Computador: Acesse http://localhost:{port}")
    print(f"📱 NOS TABLETS/CELULARES, ACESSE: {url}")
    print("*"*60 + "\n")

    # 5. Abre o navegador do computador automaticamente
    Timer(1.5, abrir_navegador, args=[f"http://localhost:{port}/login_admin"]).start()

    # 6. Cria a aplicação Flask
    app = create_app(Config)
    
    # 7. Inicia o Servidor (Host 0.0.0.0 permite acesso externo)
    # A opção debug=False é mais segura para produção e evita reload duplo
    app.run(host='0.0.0.0', port=port, debug=False)