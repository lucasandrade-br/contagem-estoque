import os
from flask import Flask, jsonify, render_template, session
from .db import init_db
from .utils import format_reais, format_datetime_br


def iniciar_job_sincronizacao(app):
    """
    Inicia job em background que exporta o banco de dados para Google Drive
    a cada 30 minutos (apenas para LOJA ou CADASTRO).
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    perfil = os.getenv('PERFIL_MAQUINA', '').strip().upper()
    caminho_drive = os.getenv('CAMINHO_GOOGLE_DRIVE', '').strip()
    
    # Só ativa job para LOJA ou CADASTRO
    if perfil not in ['LOJA', 'CADASTRO'] or not caminho_drive:
        return
    
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.sync_drive import exportar_para_nuvem
        
        scheduler = BackgroundScheduler()
        
        # Executa a cada 30 minutos
        scheduler.add_job(
            func=lambda: exportar_para_nuvem(caminho_drive),
            trigger="interval",
            minutes=30,
            id='sync_drive_job',
            name='Exportar banco para Google Drive',
            replace_existing=True
        )
        
        scheduler.start()
        app.logger.info(f"✅ Job de sincronização iniciado (a cada 30 min) - Perfil: {perfil}")
        
        # Garante que scheduler para quando Flask parar
        import atexit
        atexit.register(lambda: scheduler.shutdown())
        
    except ImportError:
        app.logger.warning("⚠️  APScheduler não está instalado. Sincronização automática desabilitada.")
        app.logger.warning("   Instale com: pip install apscheduler")


def create_app(config_object=None):
    app = Flask(__name__, template_folder='templates', static_folder='static')

    if config_object:
        app.config.from_object(config_object)
    else:
        # Configurações padrão
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
        app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
        app.config['DATABASE'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'database.db')

    # Ensure upload folder exists
    os.makedirs(app.config.get('UPLOAD_FOLDER', 'uploads'), exist_ok=True)

    # Database
    init_db(app)

    # Filters
    app.add_template_filter(format_reais, name='reais')
    app.add_template_filter(format_datetime_br, name='datetime_br')

    # Make sessions permanent (use PERMANENT_SESSION_LIFETIME)
    @app.before_request
    def make_session_permanent():
        session.permanent = True

    # Context processor para injetar variáveis de perfil em todos os templates
    @app.context_processor
    def inject_perfil():
        from dotenv import load_dotenv
        load_dotenv()
        perfil = os.getenv('PERFIL_MAQUINA', 'LOJA').strip().upper()
        return {
            'PERFIL_SISTEMA': perfil,
            'MODO_LEITURA': perfil == 'GERENTE',
            'OCULTAR_CONTAGEM': perfil in ['GERENTE', 'CADASTRO']
        }

    # Blueprints
    from .blueprints.auth import bp as auth_bp
    from .blueprints.estoque import bp as estoque_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.relatorios import bp as relatorios_bp
    from .blueprints.api import bp as api_bp
    from .blueprints.lotes import bp as lotes_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(estoque_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(relatorios_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(lotes_bp)

    # Inicializar job de sincronização para LOJA/CADASTRO
    iniciar_job_sincronizacao(app)

    # Error handlers
    @app.errorhandler(404)
    def pagina_nao_encontrada(error):
        return render_template('erro_404.html'), 404

    @app.errorhandler(500)
    def erro_interno(error):
        return render_template('erro_500.html', erro=str(error)), 500

    @app.errorhandler(Exception)
    def handle_exception(exc):
        if hasattr(exc, 'code'):
            return exc
        # Print to stderr for debugging
        import traceback
        traceback.print_exc()
        return jsonify({'erro': 'Erro interno do servidor', 'detalhes': str(exc)}), 500

    return app
