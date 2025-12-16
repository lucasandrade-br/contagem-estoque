import os
import shutil
import socket
import webbrowser
import time
from datetime import datetime
from threading import Timer
from app import create_app  # Importa a factory
from config import Config

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

if __name__ == "__main__":
    print("="*50)
    print("🥐 SISTEMA DE ESTOQUE - INICIANDO")
    print("="*50)

    # 1. Executa Backup
    fazer_backup()

    # 2. Descobre IP para os Tablets
    ip = obter_ip_local()
    port = 5000
    url = f"http://{ip}:{port}"

    print("\n" + "*"*50)
    print(f"🚀 SISTEMA ONLINE!")
    print(f"💻 No Computador: Acesse http://localhost:{port}")
    print(f"📱 NOS TABLETS/CELULARES, ACESSE: {url}")
    print("*"*50 + "\n")

    # 3. Abre o navegador do computador automaticamente
    Timer(1.5, abrir_navegador, args=[f"http://localhost:{port}/login_admin"]).start()

    # 4. Cria a aplicação Flask
    app = create_app(Config)
    
    # 5. Inicia o Servidor (Host 0.0.0.0 permite acesso externo)
    # A opção debug=False é mais segura para produção e evita reload duplo
    app.run(host='0.0.0.0', port=port, debug=False)