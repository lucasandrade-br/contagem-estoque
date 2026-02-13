import os
from datetime import date, datetime, timedelta
from flask import Flask, jsonify, render_template, session
from .db import init_db, get_db
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

    def _garantir_colunas_financeiras():
        """Garante que estoque_saldos tenha valor_total e custo_medio sem sobrescrever dados existentes."""
        db = get_db()
        cols = {row['name'] for row in db.execute('PRAGMA table_info(estoque_saldos)').fetchall()}

        precisa_seed = False
        if 'valor_total' not in cols:
            db.execute('ALTER TABLE estoque_saldos ADD COLUMN valor_total REAL NOT NULL DEFAULT 0.0')
            precisa_seed = True
        if 'custo_medio' not in cols:
            db.execute('ALTER TABLE estoque_saldos ADD COLUMN custo_medio REAL NOT NULL DEFAULT 0.0')
            precisa_seed = True

        if not precisa_seed:
            row = db.execute(
                '''SELECT COUNT(*) AS faltantes FROM estoque_saldos
                   WHERE saldo <> 0 AND valor_total = 0'''
            ).fetchone()
            precisa_seed = row and row['faltantes'] > 0

        if precisa_seed:
            db.execute('''
                UPDATE estoque_saldos es
                SET valor_total = CASE
                    WHEN valor_total = 0 THEN COALESCE((SELECT COALESCE(p.preco_custo, 0) * es.saldo FROM produtos p WHERE p.id = es.produto_id), 0)
                    ELSE valor_total
                END
            ''')
            db.execute('''
                UPDATE estoque_saldos
                SET custo_medio = CASE WHEN saldo <> 0 THEN valor_total / saldo ELSE 0 END
            ''')
            db.commit()

    # Snapshot diário do dia anterior (preenche gaps até ontem)
    def _gerar_snapshot_dia(db, data_ref):
        sql = '''
            SELECT es.produto_id, SUM(es.saldo) AS saldo, SUM(es.valor_total) AS valor_total
            FROM estoque_saldos es
            JOIN produtos p ON p.id = es.produto_id
            WHERE p.ativo = 1 AND p.controla_estoque = 1
            GROUP BY es.produto_id
        '''
        rows = db.execute(sql).fetchall()
        inseridos = 0
        for r in rows:
            saldo = float(r['saldo'] or 0)
            if saldo <= 0:
                continue
            valor_total = float(r['valor_total'] or 0)
            custo = (valor_total / saldo) if saldo > 0 else 0.0
            db.execute(
                '''
                INSERT OR IGNORE INTO saldos_historico 
                (data_ref, produto_id, quantidade, preco_custo_unitario, valor_total)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (data_ref.isoformat(), r['produto_id'], saldo, custo, valor_total)
            )
            inseridos += 1

        db.execute(
            '''
            INSERT INTO logs_auditoria (acao, descricao, data_hora)
            VALUES (?, ?, ?)
            ''',
            (
                'SNAPSHOT_SALDO',
                f"Snapshot gerado para {data_ref.isoformat()}: {inseridos} produto(s)",
                datetime.now().isoformat()
            )
        )

    def _gerar_snapshots_pendentes():
        ontem = date.today() - timedelta(days=1)
        if ontem < date(1970, 1, 1):  # guard-rail
            return

        db = get_db()
        row = db.execute('SELECT MAX(data_ref) AS max_ref FROM saldos_historico').fetchone()
        max_ref = row['max_ref'] if row else None

        if max_ref:
            try:
                inicio = date.fromisoformat(max_ref) + timedelta(days=1)
            except ValueError:
                inicio = ontem
        else:
            inicio = ontem

        if inicio > ontem:
            return

        dia = inicio
        while dia <= ontem:
            _gerar_snapshot_dia(db, dia)
            dia += timedelta(days=1)

        db.commit()

    with app.app_context():
        try:
            _garantir_colunas_financeiras()
            _gerar_snapshots_pendentes()
        except Exception:
            # Não bloquear startup; logar no stderr
            import traceback
            traceback.print_exc()

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
