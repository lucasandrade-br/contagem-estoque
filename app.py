"""
Aplicação Flask para o sistema de Contagem de Estoque Padaria.
VERSÃO ESTÁVEL - CORRIGIDA (SEM DEPENDÊNCIA DE FLASK-SESSION)
"""

from flask import Flask, render_template, g, session, redirect, url_for, request, flash, jsonify, send_file
import sqlite3
import os
import csv
import io
import math
import pandas as pd
import openpyxl
import traceback
import sys
from openpyxl.styles import Font, Alignment
import socket
import qrcode
from datetime import date, datetime, timedelta

app = Flask(__name__)

@app.template_filter('reais')
def format_reais(valor):
    """
    Transforma 1234.5 em '1.234,50'
    Transforma 10000 em '10.000,00'
    """
    if valor is None:
        valor = 0
    try:
        # Formata para padrão americano: 1,234.50
        valor_formatado = "{:,.2f}".format(float(valor))
        
        # Troca a vírgula por X, ponto por vírgula, e X por ponto (Gambiarra clássica e segura)
        return valor_formatado.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return valor



# Configuração Básica
app.secret_key = 'chave_secreta_padaria_segura'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

# Caminhos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'database', 'padaria.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')

# Garante que pastas existam
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB limite

# --- CONEXÃO COM BANCO ---
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def get_local_ip():
    """Retorna o IP local da máquina tentando conectar a um host público (não envia dados)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # não precisamos realmente enviar dados; conectar retorna o IP local utilizado
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        try:
            s.close()
        except Exception:
            pass
    return ip

# --- ROTAS PRINCIPAIS ---

@app.route('/')
def index():
    # Home: Lista apenas estoquistas ativos
    db = get_db()
    cursor = db.execute("SELECT * FROM usuarios WHERE funcao != 'Gerente' AND ativo = 1 ORDER BY nome")
    usuarios = cursor.fetchall()
    # Passa o IP local para a template (usado no modal QR)
    local_ip = get_local_ip()
    return render_template('index.html', usuarios=usuarios, local_ip=local_ip)

@app.route('/selecionar_usuario/<int:user_id>')
def selecionar_usuario(user_id):
    db = get_db()
    # Verifica inventário aberto
    cursor = db.execute("SELECT id FROM inventarios WHERE status = 'Aberto' LIMIT 1")
    if not cursor.fetchone():
        return render_template('erro_inventario.html'), 403
    # Busca usuário e seta função na sessão (isso permitirá permissões diferenciadas)
    usuario = db.execute('SELECT * FROM usuarios WHERE id = ? AND ativo = 1', (user_id,)).fetchone()
    if not usuario:
        return render_template('erro_inventario.html'), 403

    session['user_id'] = usuario['id']
    session['funcao'] = usuario['funcao']
    # Marca gerente se for o caso
    session['is_gerente'] = True if usuario['funcao'] == 'Gerente' else session.get('is_gerente', False)

    return redirect(url_for('setores'))

@app.route('/setores')
def setores():
    
    db = get_db()
    cursor = db.execute('SELECT * FROM setores WHERE ativo=1 ORDER BY nome')
    return render_template('setores.html', setores=cursor.fetchall())


@app.route('/setor/<int:setor_id>')
def setor(setor_id):
    db = get_db()
    # Dados do setor
    setor = db.execute('SELECT * FROM setores WHERE id = ? AND ativo=1', (setor_id,)).fetchone()
    if not setor: return redirect(url_for('setores'))

    # Inventário aberto para contagem
    inv = db.execute("SELECT id FROM inventarios WHERE status = 'Aberto' LIMIT 1").fetchone()
    inv_id = inv['id'] if inv else None

    # Locais com contagem de itens
    sql = '''
        SELECT l.*, 
               (SELECT COUNT(*) FROM contagens c WHERE c.id_local = l.id AND c.id_inventario = ?) as total_itens,
               s.nome as setor_nome
        FROM locais l
        JOIN setores s ON l.id_setor = s.id
        WHERE l.id_setor = ?
        ORDER BY l.nome
    '''
    locais = db.execute(sql, (inv_id if inv_id else 0, setor_id)).fetchall()
    
    return render_template('locais.html', setor=dict(setor), locais=[dict(l) for l in locais])

# --- ÁREA ADMINISTRATIVA ---

@app.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '').strip()
        
        db = get_db()
        gerente = db.execute(
            "SELECT * FROM usuarios WHERE funcao = 'Gerente' AND nome = ? AND senha = ?",
            (usuario, senha)
        ).fetchone()
        
        if gerente:
            session['user_id'] = gerente['id']
            session['is_gerente'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('Acesso negado.', 'error')
            
    return render_template('login_admin.html')

@app.route('/dashboard')
def dashboard():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status = 'Aberto' LIMIT 1").fetchone()
    inventario_aberto = dict(inv) if inv else None
    
    # Inicializa variáveis com valores padrão para não quebrar o HTML se não houver inventário
    kpis = {
        'total_locais': 0, 
        'locais_concluidos': 0, 
        'percentual': 0, 
        'valor_total_estoque': 0.0
    }
    relatorio, progresso, logs, nao_contados = [], [], [], []

    if inventario_aberto:
        inv_id = inventario_aberto['id']
        
        # 1. KPIs de Progresso
        total_loc = db.execute('SELECT COUNT(*) as t FROM locais').fetchone()['t']
        concluidos = db.execute('SELECT COUNT(*) as t FROM locais WHERE status = 2').fetchone()['t']
        
        # Atualiza os KPIs básicos
        kpis['total_locais'] = total_loc
        kpis['locais_concluidos'] = concluidos
        kpis['percentual'] = round((concluidos/total_loc*100), 1) if total_loc > 0 else 0

        # --- 2. CÁLCULO FINANCEIRO (A CORREÇÃO ESTÁ AQUI) ---
        # Multiplica: Qtd Contada * Fator da Unidade * Preço de Custo
        sql_financeiro = '''
            SELECT SUM(c.quantidade * COALESCE(pu.fator_conversao, 1.0) * COALESCE(p.preco_custo, 0)) as total_reais
            FROM contagens c
            JOIN produtos p ON c.id_produto = p.id
            LEFT JOIN produtos_unidades pu ON p.id = pu.id_produto AND c.id_unidade_usada = pu.id_unidade
            WHERE c.id_inventario = ?
        '''
        resultado_fin = db.execute(sql_financeiro, (inv_id,)).fetchone()
        
        # Se o resultado for None (nenhuma contagem), assume 0.0
        valor_calculado = resultado_fin['total_reais'] if resultado_fin and resultado_fin['total_reais'] else 0.0
        kpis['valor_total_estoque'] = valor_calculado
        # ----------------------------------------------------

        # 3. Progresso Setores
        sql_prog = '''
            SELECT 
                s.nome, 
                COUNT(l.id) as total_locais, 
                SUM(CASE WHEN l.status=2 THEN 1 ELSE 0 END) as concluidos
            FROM setores s 
            LEFT JOIN locais l ON s.id = l.id_setor
            GROUP BY s.id
            ORDER BY s.nome
        '''
        progresso = []
        for r in db.execute(sql_prog).fetchall():
            row = dict(r)
            if row['total_locais'] > 0:
                row['percentual'] = round((row['concluidos'] / row['total_locais'] * 100), 1)
            else:
                row['percentual'] = 0
            progresso.append(row)

        # 4. Logs e Não Contados
        logs = [dict(r) for r in db.execute('SELECT * FROM logs_auditoria ORDER BY id DESC LIMIT 10').fetchall()]
        
        sql_nao = '''
            SELECT count(*) as total FROM produtos p 
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ? 
            WHERE c.id IS NULL AND p.ativo = 1
        '''
        # Agora retornamos apenas o número total de pendências para o card de alerta
        total_pendencias = db.execute(sql_nao, (inv_id,)).fetchone()['total']
        
        # Ajuste: passamos o número como lista vazia ou cheia para compatibilidade, 
        # ou passamos uma variável separada. Vamos passar 'itens_nao_contados' como o número para simplificar a lógica do botão.
        nao_contados = total_pendencias 

        # 5. RELATÓRIO CONSOLIDADO
        sql_rel = '''
            SELECT c.quantidade, u.sigla, p.id as prod_id, p.nome,
                   p.id_unidade_padrao, u_pad.sigla as padrao_sigla,
                   COALESCE(pu.fator_conversao, 1.0) as fator,
                   p.preco_custo
            FROM contagens c
            JOIN produtos p ON c.id_produto = p.id
            JOIN unidades_medida u ON c.id_unidade_usada = u.id
            JOIN unidades_medida u_pad ON p.id_unidade_padrao = u_pad.id
            LEFT JOIN produtos_unidades pu ON p.id = pu.id_produto AND c.id_unidade_usada = pu.id_unidade
            WHERE c.id_inventario = ?
        '''
        rows = db.execute(sql_rel, (inv_id,)).fetchall()
        
        temp_rel = {}
        for r in rows:
            pid = r['prod_id']
            sigla = r['sigla']
            qtd = r['quantidade']
            
            if pid not in temp_rel:
                temp_rel[pid] = {
                    'produto_id': pid, # Importante para o link de detalhe
                    'nome': r['nome'],
                    'padrao': r['padrao_sigla'],
                    'soma_por_unidade': {}, # Novo: Dicionário para agrupar (ex: {'CX': 10, 'UN': 2})
                    'total_consolidado': 0.0,
                    'preco_custo': r['preco_custo'] or 0
                }
            
            # Agrupamento por unidade (Soma quantidades da mesma sigla)
            if sigla not in temp_rel[pid]['soma_por_unidade']:
                temp_rel[pid]['soma_por_unidade'][sigla] = 0
            temp_rel[pid]['soma_por_unidade'][sigla] += qtd
            
            # Soma convertido
            temp_rel[pid]['total_consolidado'] += (qtd * r['fator'])
        
        # Formata para lista final
        for pid, dados in temp_rel.items():
            # Constrói string "10 CX, 5 UN"
            partes = []
            for sigla, total_unid in dados['soma_por_unidade'].items():
                # Formata removendo .0 se for inteiro (ex: 10.0 -> 10)
                qtd_fmt = int(total_unid) if total_unid.is_integer() else total_unid
                partes.append(f"{qtd_fmt} {sigla}")
            
            resumo_detalhes = ", ".join(partes)
            
            relatorio.append({
                'produto_id': dados['produto_id'],
                'produto_nome': dados['nome'],
                'detalhamento': resumo_detalhes,
                'total_final': round(dados['total_consolidado'], 2),
                'unidade_padrao': dados['padrao'],
                'valor_total': round(dados['total_consolidado'] * dados['preco_custo'], 2) # Valor monetário
            })

    # Contar ocorrências pendentes (para alerta no dashboard)
    ocorrencias_pendentes = 0
    if inventario_aberto:
        inv_id = inventario_aberto['id']
        result = db.execute(
            "SELECT COUNT(*) as count FROM ocorrencias WHERE id_inventario = ? AND resolvido = 0",
            (inv_id,)
        ).fetchone()
        ocorrencias_pendentes = result['count'] if result else 0

    return render_template('dashboard.html', 
                         inventario_aberto=inventario_aberto,
                         kpis=kpis, 
                         relatorio=relatorio,
                         progresso_setores=progresso,
                         logs_recentes=logs,
                         total_pendencias=nao_contados if inventario_aberto else 0,
                         ocorrencias_pendentes=ocorrencias_pendentes,
                         is_gerente=True)


@app.route('/gerar_qrcode')
def gerar_qrcode():
    """Gera um QR Code PNG em memória contendo a URL de acesso local (http://IP:5000)."""
    ip = get_local_ip()
    url = f"http://{ip}:5000"

    # Gera QR Code
    try:
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png', download_name='qrcode.png')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/monitoramento')
def monitoramento():
    """Visão global: Progresso setores + Relatório consolidado completo + Alertas."""
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status = 'Aberto' LIMIT 1").fetchone()
    inventario_aberto = dict(inv) if inv else None
    
    progresso_setores, relatorio, alertas = [], [], []

    if inventario_aberto:
        inv_id = inventario_aberto['id']
        
        # Query 1: Progresso Setores
        sql_prog = '''
            SELECT s.id, s.nome, COUNT(l.id) as total, 
                   SUM(CASE WHEN l.status=2 THEN 1 ELSE 0 END) as concluidos
            FROM setores s LEFT JOIN locais l ON s.id = l.id_setor
            GROUP BY s.id ORDER BY s.nome
        '''
        for r in db.execute(sql_prog).fetchall():
            row = dict(r)
            row['percentual'] = round((row['concluidos']/row['total']*100), 1) if row['total'] > 0 else 0
            progresso_setores.append(row)
        
        # Query 2: Relatório Consolidado (Conversão + Financeiro)
        sql_rel = '''
            SELECT c.id, c.quantidade, p.id as prod_id, p.nome as prod_nome, p.preco_custo,
                   u.sigla as unit_sigla, u_pad.sigla as padrao_sigla,
                   COALESCE(pu.fator_conversao, 1.0) as fator
            FROM contagens c
            JOIN produtos p ON c.id_produto = p.id
            JOIN unidades_medida u ON c.id_unidade_usada = u.id
            JOIN unidades_medida u_pad ON p.id_unidade_padrao = u_pad.id
            LEFT JOIN produtos_unidades pu ON p.id = pu.id_produto AND c.id_unidade_usada = pu.id_unidade
            WHERE c.id_inventario = ?
        '''
        rows = db.execute(sql_rel, (inv_id,)).fetchall()
        
        from collections import defaultdict
        
        temp_rel = {}
        for r in rows:
            pid = r['prod_id']
            if pid not in temp_rel:
                temp_rel[pid] = {
                    'nome': r['prod_nome'],
                    'padrao_sigla': r['padrao_sigla'],
                    'preco_custo': r['preco_custo'] or 0.0,
                    'soma_por_unidade': defaultdict(float),  # Agrupa por sigla
                    'total_std': 0.0,  # Total em unidade padrão
                    'total_valor': 0.0
                }
            # Converte para unidade padrão
            fator = float(r['fator']) if r['fator'] else 1.0
            qtd_convertida = r['quantidade'] * fator
            
            # Agrupa por unidade e quantidade
            temp_rel[pid]['soma_por_unidade'][r['unit_sigla']] += r['quantidade']
            # Calcula total em unidade padrão
            temp_rel[pid]['total_std'] += qtd_convertida
            # Calcula valor (quantidade convertida × preço)
            temp_rel[pid]['total_valor'] += qtd_convertida * temp_rel[pid]['preco_custo']
        
        for pid, dados in temp_rel.items():
            # Monta detalhamento: "10.5 CX, 2 UN"
            detalhes_str = ", ".join([
                f"{int(qty) if qty == int(qty) else round(qty, 2)} {unidade}"
                for unidade, qty in sorted(dados['soma_por_unidade'].items())
            ])
            relatorio.append({
                'produto_id': pid,
                'produto_nome': dados['nome'],
                'detalhamento': detalhes_str,
                'total_padrao': round(dados['total_std'], 2),
                'unidade_padrao_sigla': dados['padrao_sigla'],
                'valor_total': round(dados['total_valor'], 2)
            })
        
        # Query 3: Contagem de Pendências (produtos não contados)
        sql_count_pendencias = '''
            SELECT COUNT(*) as total FROM produtos p
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            WHERE c.id IS NULL AND p.ativo = 1
        '''
        total_pendencias = db.execute(sql_count_pendencias, (inv_id,)).fetchone()['total']
    else:
        total_pendencias = 0

    return render_template('monitoramento.html',
                         inventario_aberto=inventario_aberto,
                         progresso_setores=progresso_setores,
                         relatorio=relatorio,
                         total_pendencias=total_pendencias,
                         is_gerente=True)


@app.route('/monitoramento/pendencias')
def monitoramento_pendencias():
    """Lista produtos não contados com paginação."""
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv: return redirect(url_for('dashboard'))
    
    inv_id = inv['id']
    pagina = request.args.get('page', 1, type=int)
    itens_por_pagina = 50
    offset = (pagina - 1) * itens_por_pagina
    
    # Query: Produtos não contados com paginação
    sql_pendencias = '''
        SELECT p.id, p.nome, p.categoria, p.preco_custo
        FROM produtos p
        LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
        WHERE c.id IS NULL AND p.ativo = 1
        ORDER BY p.nome
        LIMIT ? OFFSET ?
    '''
    pendencias = [dict(r) for r in db.execute(sql_pendencias, (inv_id, itens_por_pagina, offset)).fetchall()]
    
    # Contagem total para paginação
    sql_count = '''
        SELECT COUNT(*) as total FROM produtos p
        LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
        WHERE c.id IS NULL AND p.ativo = 1
    '''
    total = db.execute(sql_count, (inv_id,)).fetchone()['total']
    total_paginas = (total + itens_por_pagina - 1) // itens_por_pagina
    
    return render_template('monitoramento_pendencias.html',
                         pendencias=pendencias,
                         pagina_atual=pagina,
                         total_paginas=total_paginas,
                         total_pendencias=total,
                         is_gerente=True)

@app.route('/monitoramento/setor/<int:setor_id>')
def monitoramento_setor(setor_id):
    """Detalhamento de um setor: locais + itens contados."""
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    db = get_db()
    setor = db.execute("SELECT * FROM setores WHERE id = ?", (setor_id,)).fetchone()
    if not setor: return redirect(url_for('monitoramento'))
    
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv: return redirect(url_for('dashboard'))
    
    inv_id = inv['id']
    
    # Query 1: Locais do setor com status
    sql_locais = '''
        SELECT l.*, COALESCE(COUNT(c.id), 0) as qtd_contagens
        FROM locais l
        LEFT JOIN contagens c ON l.id = c.id_local AND c.id_inventario = ?
        WHERE l.id_setor = ?
        GROUP BY l.id ORDER BY l.nome
    '''
    locais = [dict(r) for r in db.execute(sql_locais, (inv_id, setor_id)).fetchall()]
    
    # Mapear status para labels
    for loc in locais:
        if loc['status'] == 0:
            loc['status_label'] = 'Pendente'
            loc['status_color'] = 'red'
        elif loc['status'] == 1:
            loc['status_label'] = 'Andamento'
            loc['status_color'] = 'yellow'
        else:
            loc['status_label'] = 'Concluído'
            loc['status_color'] = 'green'
    
    # Query 2: Itens contados neste setor (Agrupado por Produto/Unidade)
    sql_itens = '''
        SELECT p.nome as prod_nome, u.sigla, SUM(c.quantidade) as total_qtd
        FROM contagens c
        JOIN produtos p ON c.id_produto = p.id
        JOIN unidades_medida u ON c.id_unidade_usada = u.id
        JOIN locais l ON c.id_local = l.id
        WHERE l.id_setor = ? AND c.id_inventario = ?
        GROUP BY p.id, u.id ORDER BY p.nome
    '''
    itens = [dict(r) for r in db.execute(sql_itens, (setor_id, inv_id)).fetchall()]

    return render_template('monitoramento_setor.html',
                         setor=dict(setor),
                         locais=locais,
                         itens=itens,
                         is_gerente=True)


@app.route('/api/detalhes_local/<int:local_id>')
def api_detalhes_local(local_id):
    """API JSON: retorna todas as contagens de um local específico no inventário aberto.
    Retorna lista de itens com: produto, quantidade, unidade, usuario, data_hora
    """
    if not session.get('is_gerente'):
        return jsonify({'error': 'Acesso negado'}), 403

    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        # Sem inventário aberto -> retorna lista vazia
        return jsonify([])

    inv_id = inv['id']

    sql = '''
        SELECT p.nome as produto, c.quantidade, um.sigla as unidade, u.nome as usuario, c.data_hora
        FROM contagens c
        JOIN produtos p ON c.id_produto = p.id
        LEFT JOIN unidades_medida um ON c.id_unidade_usada = um.id
        LEFT JOIN usuarios u ON c.id_usuario = u.id
        WHERE c.id_local = ? AND c.id_inventario = ?
        ORDER BY c.data_hora DESC
    '''
    rows = db.execute(sql, (local_id, inv_id)).fetchall()

    itens = []
    for r in rows:
        itens.append({
            'produto': r['produto'],
            'quantidade': r['quantidade'],
            'unidade': r['unidade'],
            'usuario': r['usuario'],
            'data_hora': r['data_hora']
        })

    return jsonify(itens)


@app.route('/api/atualizar_produto_rapido', methods=['POST'])
def api_atualizar_produto_rapido():
    """Atualização rápida de fatores de conversão para um produto.
    Somente Gerente ou Estoquista Chefe podem executar.
    Payload: { produto_id: int, unidades: [ { id_unidade: int, fator_conversao: float }, ... ] }
    """
    # Permissão: gerente ou estoquista chefe
    if not (session.get('is_gerente') or session.get('funcao') == 'Estoquista Chefe'):
        return jsonify({'error': 'Acesso negado'}), 403

    data = request.get_json() or {}
    produto_id = data.get('produto_id')
    unidades = data.get('unidades', [])

    if not produto_id or not isinstance(unidades, list):
        return jsonify({'error': 'Dados inválidos'}), 400

    db = get_db()
    try:
        for u in unidades:
            uid = int(u.get('id_unidade'))
            fator = float(u.get('fator_conversao'))
            # Upsert: substitui ou insere o fator
            db.execute('''
                INSERT OR REPLACE INTO produtos_unidades (id_produto, id_unidade, fator_conversao)
                VALUES (?, ?, ?)
            ''', (produto_id, uid, fator))
        db.commit()
        return jsonify({'sucesso': True})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/registrar_ocorrencia', methods=['POST'])
def api_registrar_ocorrencia():
    """Registra uma ocorrência (item não cadastrado ou avulso).
    Aceita Multipart/Form-Data.
    Campos: local_id, nome, quantidade, unidade_id, foto (arquivo opcional).
    """
    if 'user_id' not in session:
        return jsonify({'sucesso': False, 'error': 'Login necessário'}), 401
    
    # Obter inventário aberto
    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto'").fetchone()
    if not inv:
        return jsonify({'sucesso': False, 'error': 'Nenhum inventário aberto'}), 400
    
    # Validar campos obrigatórios
    local_id = request.form.get('local_id', type=int)
    nome = request.form.get('nome', '').strip()
    quantidade = request.form.get('quantidade', type=float)
    unidade_id = request.form.get('unidade_id', type=int)
    
    if not local_id or not nome or not quantidade or not unidade_id:
        return jsonify({'sucesso': False, 'error': 'Campos obrigatórios: local_id, nome, quantidade, unidade_id'}), 400
    
    if quantidade <= 0:
        return jsonify({'sucesso': False, 'error': 'Quantidade deve ser maior que zero'}), 400
    
    foto_path = None
    
    # Processar foto se enviada
    if 'foto' in request.files:
        foto_file = request.files['foto']
        if foto_file and foto_file.filename:
            try:
                # Criar diretório se não existir (dentro de static/)
                ocorrencias_dir = os.path.join(app.root_path, 'static', 'uploads', 'ocorrencias')
                if not os.path.exists(ocorrencias_dir):
                    os.makedirs(ocorrencias_dir)
                
                # Gerar nome único para a foto
                import uuid
                ext = os.path.splitext(foto_file.filename)[1]
                unique_name = f"ocorrencia_{uuid.uuid4().hex}{ext}"
                full_path = os.path.join(ocorrencias_dir, unique_name)
                
                # Salvar arquivo e guardar caminho relativo para HTML
                foto_file.save(full_path)
                foto_path = f'/static/uploads/ocorrencias/{unique_name}'
            except Exception as e:
                # Se falhar ao salvar foto, continua sem ela (não é crítico)
                print(f"Erro ao salvar foto: {e}")
                foto_path = None
    
    # Inserir ocorrência no banco
    try:
        db.execute('''
            INSERT INTO ocorrencias (id_inventario, id_local, id_usuario, nome_identificado, quantidade, id_unidade, foto_path, resolvido)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        ''', (inv['id'], local_id, session.get('user_id'), nome, quantidade, unidade_id, foto_path))
        db.commit()
        
        return jsonify({'sucesso': True, 'message': 'Ocorrência registrada com sucesso'}), 200
    except Exception as e:
        db.rollback()
        return jsonify({'sucesso': False, 'error': str(e)}), 500


@app.route('/monitoramento/produto/<int:produto_id>')
def detalhe_produto_inventario(produto_id):
    """Detalhamento de um produto: auditoria completa de todas as contagens."""
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv: return redirect(url_for('dashboard'))
    
    inv_id = inv['id']
    
    # Produto info
    produto = db.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    if not produto: return redirect(url_for('monitoramento'))
    
    # Query consolidado: total contado + valor
    sql_resumo = '''
        SELECT 
            COALESCE(SUM(c.quantidade * COALESCE(pu.fator_conversao, 1.0)), 0.0) as total_padrao,
            COALESCE(SUM(c.quantidade * COALESCE(pu.fator_conversao, 1.0) * ?), 0.0) as valor_total
        FROM contagens c
        LEFT JOIN produtos_unidades pu ON c.id_produto = pu.id_produto AND c.id_unidade_usada = pu.id_unidade
        WHERE c.id_produto = ? AND c.id_inventario = ?
    '''
    resumo = db.execute(sql_resumo, (float(produto['preco_custo'] or 0.0), produto_id, inv_id)).fetchone()
    
    # Query detalhada: todas as contagens deste produto
    sql_detalhes = '''
        SELECT 
            c.data_hora, s.nome as setor, l.nome as local, u.nome as usuario,
            c.quantidade, um.sigla as unidade
        FROM contagens c
        JOIN locais l ON c.id_local = l.id
        JOIN setores s ON l.id_setor = s.id
        JOIN usuarios u ON c.id_usuario = u.id
        JOIN unidades_medida um ON c.id_unidade_usada = um.id
        WHERE c.id_produto = ? AND c.id_inventario = ?
        ORDER BY c.data_hora DESC
    '''
    detalhes = [dict(r) for r in db.execute(sql_detalhes, (produto_id, inv_id)).fetchall()]
    
    return render_template('detalhe_produto.html',
                         produto=dict(produto),
                         resumo=dict(resumo),
                         detalhes=detalhes,
                         is_gerente=True)

# --- AÇÕES DE INVENTÁRIO ---

@app.route('/abrir_inventario', methods=['POST'])
def abrir_inventario():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()
    if not db.execute("SELECT id FROM inventarios WHERE status='Aberto'").fetchone():
        db.execute("INSERT INTO inventarios (data_criacao, status, descricao) VALUES (?, ?, ?)",
                   (date.today().isoformat(), 'Aberto', 'Iniciado pelo Gerente'))
        db.commit()
    return redirect(url_for('dashboard'))


@app.route('/fechar_inventario', methods=['POST'])
def fechar_inventario():
    """Fecha o inventário aberto e salva um snapshot do status dos locais.
    Fluxo:
    - Identifica inventário aberto
    - TRAVA: Verifica se há ocorrências pendentes (resolvido=0)
    - Remove snapshots anteriores para esse inventário
    - Coleta todos os locais (id, status) e insere em historico_status_locais
    - Marca inventário como Fechado
    """
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        flash('Nenhum inventário aberto para fechar.', 'error')
        return redirect(url_for('dashboard'))

    inv_id = inv['id']
    
    # TRAVA: Verificar se há ocorrências pendentes
    ocorrencias_pendentes = db.execute(
        "SELECT COUNT(*) as count FROM ocorrencias WHERE id_inventario = ? AND resolvido = 0",
        (inv_id,)
    ).fetchone()
    
    if ocorrencias_pendentes['count'] > 0:
        flash(f'❌ Existem {ocorrencias_pendentes["count"]} ocorrências pendentes! Resolva todas antes de fechar o inventário.', 'error')
        return redirect(url_for('admin_ocorrencias'))

    # 1) Apaga snapshots anteriores para este inventário
    db.execute("DELETE FROM historico_status_locais WHERE id_inventario = ?", (inv_id,))

    # 2) Seleciona todos os locais atuais
    locais = db.execute("SELECT id, status FROM locais").fetchall()
    entries = [(inv_id, l['id'], l['status']) for l in locais]

    # 3) Insere o snapshot (se houver locais)
    if entries:
        db.executemany(
            "INSERT INTO historico_status_locais (id_inventario, id_local, status_registrado) VALUES (?, ?, ?)",
            entries
        )

    # 4) Fecha o inventário
    db.execute("UPDATE inventarios SET status='Fechado', data_fechamento = CURRENT_TIMESTAMP WHERE id = ? AND status='Aberto'", (inv_id,))
    db.commit()
    flash('Inventário fechado e snapshot salvo.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/iniciar_novo_inventario', methods=['POST'])
def iniciar_novo_inventario():
    """Inicia um novo inventário e reseta o status de todos os locais para 0."""
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()

    # Cria novo inventário aberto
    db.execute("INSERT INTO inventarios (data_criacao, status, descricao) VALUES (?, ?, ?)",
               (date.today().isoformat(), 'Aberto', 'Iniciado pelo Gerente - Novo Inventário'))

    # Reseta todos os locais para status 0
    db.execute("UPDATE locais SET status = 0")
    db.commit()
    flash('Novo inventário iniciado. Todos os locais foram resetados.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/recuperar_ultimo_inventario', methods=['POST'])
def recuperar_ultimo_inventario():
    """Recupera o último inventário existente, marca como Aberto e restaura o snapshot de status dos locais."""
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()

    last = db.execute("SELECT id FROM inventarios ORDER BY id DESC LIMIT 1").fetchone()
    if not last:
        flash('Nenhum inventário encontrado para recuperar.', 'error')
        return redirect(url_for('dashboard'))

    inv_id = last['id']

    # Marca como aberto
    db.execute("UPDATE inventarios SET status='Aberto' WHERE id = ?", (inv_id,))

    # Opcional: reset total antes de aplicar histórico para garantir estado limpo
    db.execute("UPDATE locais SET status = 0")

    # Busca snapshot e aplica nos locais
    rows = db.execute("SELECT id_local, status_registrado FROM historico_status_locais WHERE id_inventario = ?", (inv_id,)).fetchall()
    for r in rows:
        db.execute("UPDATE locais SET status = ? WHERE id = ?", (r['status_registrado'], r['id_local']))

    db.commit()
    flash('Inventário recuperado e locais restaurados a partir do snapshot.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/editar_quantidade', methods=['POST'])
def editar_quantidade():
    if not session.get('is_gerente'): return jsonify({'erro': 'Acesso negado'}), 403
    data = request.get_json()
    
    db = get_db()
    
    # Busca contagem antiga para log
    antiga = db.execute('SELECT * FROM contagens WHERE id=?', (data['contagem_id'],)).fetchone()
    
    db.execute('UPDATE contagens SET quantidade = ? WHERE id = ?', (data['nova_quantidade'], data['contagem_id']))
    
    # Log
    desc = f"Alterou de {antiga['quantidade']} para {data['nova_quantidade']}. Motivo: {data['motivo']}"
    db.execute("INSERT INTO logs_auditoria (acao, descricao, data_hora) VALUES (?, ?, ?)",
               ('CORRECAO_GERENTE', desc, datetime.now().isoformat()))
    db.commit()
    return jsonify({'sucesso': True})

@app.route('/exportar_csv')
def exportar_csv():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv: return redirect(url_for('dashboard'))

    # Query completa para exportação
    sql = '''
        SELECT c.data_hora, s.nome as setor, l.nome as local, p.nome as produto, 
               c.quantidade, u.sigla as unidade, us.nome as usuario
        FROM contagens c
        JOIN produtos p ON c.id_produto = p.id
        JOIN locais l ON c.id_local = l.id
        JOIN setores s ON l.id_setor = s.id
        JOIN unidades_medida u ON c.id_unidade_usada = u.id
        JOIN usuarios us ON c.id_usuario = us.id
        WHERE c.id_inventario = ?
    '''
    rows = db.execute(sql, (inv['id'],)).fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Data', 'Setor', 'Local', 'Produto', 'Qtd', 'Unidade', 'Usuario'])
    for r in rows: writer.writerow(list(r))
    
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), 
                     mimetype='text/csv', as_attachment=True, download_name='inventario.csv')

# --- OPERACIONAL (TABLET) ---

@app.route('/contagem/<int:local_id>')
def contagem(local_id):
    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto'").fetchone()
    if not inv: return redirect(url_for('setores'))
    
    local = db.execute("SELECT * FROM locais WHERE id = ?", (local_id,)).fetchone()
    
    # Busca produtos e suas unidades permitidas
    produtos = [dict(r) for r in db.execute("SELECT * FROM produtos WHERE ativo=1 AND UPPER(categoria) != 'NAO CONTA' AND UPPER(categoria) != 'NÃO CONTA' ORDER BY nome").fetchall()]
    
    # Busca tabela de junção N:N
    unidades_rows = db.execute('''
        SELECT pu.*, u.sigla, u.nome, u.permite_decimal 
        FROM produtos_unidades pu JOIN unidades_medida u ON pu.id_unidade = u.id
    ''').fetchall()
    
    # Mapa de unidades por produto
    mapa_unidades = {}
    for row in unidades_rows:
        pid = row['id_produto']
        if pid not in mapa_unidades: mapa_unidades[pid] = []
        mapa_unidades[pid].append(dict(row))
        
    for p in produtos:
        p['unidades_permitidas'] = mapa_unidades.get(p['id'], [])

    unidades = [dict(r) for r in db.execute("SELECT * FROM unidades_medida ORDER BY sigla").fetchall()]

    historico = db.execute('''
        SELECT c.*, p.nome as produto_nome, u.sigla as unidade_sigla 
        FROM contagens c 
        JOIN produtos p ON c.id_produto = p.id
        JOIN unidades_medida u ON c.id_unidade_usada = u.id
        WHERE c.id_local = ? AND c.id_inventario = ? ORDER BY c.id DESC
    ''', (local_id, inv['id'])).fetchall()

    return render_template('contagem.html', local=dict(local), produtos=produtos, unidades=unidades,
                           historico=[dict(h) for h in historico], inventario_id=inv['id'])


@app.route('/salvar_contagem', methods=['POST'])
def salvar_contagem():
    # 1. Segurança e Dados
    if 'user_id' not in session: return jsonify({'erro': 'Login necessário'}), 401
    data = request.get_json()
    
    db = get_db()
    
    try:
        # 2. Verifica Inventário Aberto
        inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
        if not inv: return jsonify({'erro': 'Nenhum inventário aberto no momento'}), 400
        
        # 3. BUSCA DADOS PARA O SNAPSHOT (Histórico)
        # Precisamos saber o preço ATUAL e a unidade PADRÃO para gravar na pedra
        produto = db.execute('''
            SELECT p.preco_custo, p.id_unidade_padrao, u.sigla as sigla_padrao
            FROM produtos p
            JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.id = ?
        ''', (data['produto_id'],)).fetchone()
        
        if not produto: return jsonify({'erro': 'Produto não encontrado'}), 404

        # 4. CÁLCULO DO FATOR DE CONVERSÃO
        fator_conversao = 1.0
        id_unidade_usada = int(data['unidade_id'])
        id_unidade_padrao = int(produto['id_unidade_padrao'])

        # Se a unidade contada for diferente da padrão, buscamos o fator no banco
        if id_unidade_usada != id_unidade_padrao:
            fator_row = db.execute('''
                SELECT fator_conversao FROM produtos_unidades 
                WHERE id_produto = ? AND id_unidade = ?
            ''', (data['produto_id'], id_unidade_usada)).fetchone()
            
            if fator_row:
                fator_conversao = float(fator_row['fator_conversao'])
            
            # Se não achar conversão cadastrada, mantém 1.0 como segurança

        # 5. CÁLCULOS FINAIS
        qtd_informada = float(data['quantidade'])
        qtd_padrao_calculada = qtd_informada * fator_conversao
        preco_snapshot = float(produto['preco_custo'] or 0)
        sigla_snapshot = produto['sigla_padrao']

        # 6. INSERÇÃO COM DADOS HISTÓRICOS (SNAPSHOT)
        db.execute('''
            INSERT INTO contagens (
                id_inventario, id_produto, id_local, id_usuario, 
                quantidade, id_unidade_usada, data_hora,
                
                -- Novos Campos de Histórico
                fator_conversao, quantidade_padrao, preco_custo_snapshot, unidade_padrao_sigla
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            inv['id'], 
            data['produto_id'], 
            data['local_id'], 
            session['user_id'], 
            qtd_informada, 
            id_unidade_usada, 
            datetime.now().isoformat(),
            
            # Valores Calculados
            fator_conversao,
            qtd_padrao_calculada,
            preco_snapshot,
            sigla_snapshot
        ))
        
        # 7. Mantém sua lógica de atualizar status do local (Pendente -> Em Andamento)
        db.execute("UPDATE locais SET status = 1 WHERE id = ? AND status = 0", (data['local_id'],))
        
        db.commit()
        return jsonify({'sucesso': True})

    except Exception as e:
        # Em caso de erro, desfaz tudo para não deixar dados pela metade
        db.rollback()
        print(f"Erro ao salvar contagem: {e}")
        return jsonify({'erro': str(e)}), 500


@app.route('/finalizar_local/<int:local_id>', methods=['POST'])
def finalizar_local(local_id):
    db = get_db()
    db.execute("UPDATE locais SET status = 2 WHERE id = ?", (local_id,))
    db.commit()
    return redirect(url_for('setores'))

# --- GESTÃO DE PRODUTOS (PAGINAÇÃO SERVER-SIDE) ---

@app.route('/admin/produtos', methods=['GET', 'POST'])
def admin_produtos():

    is_autorizado = session.get('is_gerente') or session.get('funcao') == 'Estoquista Chefe'
        
    if not is_autorizado:
        # Se for uma tentativa via AJAX (Modal), retornamos erro JSON em vez de redirecionar
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'sucesso': False, 'error': 'Permissão negada. Apenas Gerentes ou Chefes.'}), 403
        return redirect(url_for('login_admin'))
    db = get_db()

    # --- LÓGICA DE SALVAR (POST) ---
    if request.method == 'POST':
        produto_id = request.form.get('produto_id')
        nome = request.form.get('nome', '').strip()
        categoria = request.form.get('categoria', '').strip()
        id_unidade_padrao = request.form.get('id_unidade_padrao')
        id_erp = request.form.get('id_erp', '').strip() or None
        gtin = request.form.get('gtin', '').strip() or None
        preco_custo = float(request.form.get('preco_custo', 0) or 0)
        preco_venda = float(request.form.get('preco_venda', 0) or 0)
        unidades_permitidas = request.form.getlist('unidades_permitidas')

        if not nome or not id_unidade_padrao:
            error_msg = 'Nome e Unidade Padrão são obrigatórios.'
            # Se for requisição AJAX, retorna JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'sucesso': False, 'error': error_msg}), 400
            flash(error_msg, 'error')
        else:
            try:
                if produto_id:
                    db.execute('''
                        UPDATE produtos
                        SET nome = ?, categoria = ?, id_unidade_padrao = ?, id_erp = ?, gtin = ?, preco_custo = ?, preco_venda = ?
                        WHERE id = ?
                    ''', (nome, categoria or None, int(id_unidade_padrao), id_erp, gtin, preco_custo, preco_venda, int(produto_id)))
                else:
                    cursor = db.execute('''
                        INSERT INTO produtos (nome, categoria, id_unidade_padrao, id_erp, gtin, preco_custo, preco_venda)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (nome, categoria or None, int(id_unidade_padrao), id_erp, gtin, preco_custo, preco_venda))
                    produto_id = cursor.lastrowid
                
                # Atualizar Relações N:N
                db.execute('DELETE FROM produtos_unidades WHERE id_produto = ?', (produto_id,))
                # Unidade Padrão
                db.execute("INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao) VALUES (?, ?, 1.0)", 
                          (produto_id, int(id_unidade_padrao)))
                # Unidades Secundárias
                for uid in unidades_permitidas:
                    uid_int = int(uid)
                    if uid_int == int(id_unidade_padrao): continue
                    fator = float(request.form.get(f'fator_{uid_int}', '0').replace(',', '.') or 0)
                    if fator > 0:
                        db.execute("INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao) VALUES (?, ?, ?)",
                                  (produto_id, uid_int, fator))
                
                db.commit()
                success_msg = 'Produto salvo com sucesso!'
                
                # Se for requisição AJAX, retorna JSON
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'sucesso': True, 'produto_id': produto_id, 'message': success_msg}), 200
                
                flash(success_msg, 'success')
            except Exception as e:
                db.rollback()
                error_msg = f'Erro: {e}'
                
                # Se for requisição AJAX, retorna JSON
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'sucesso': False, 'error': error_msg}), 500
                
                flash(error_msg, 'error')
        
        # Se não for AJAX, redireciona
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            return redirect(url_for('admin_produtos'))

    # --- LÓGICA DE BUSCA E PAGINAÇÃO (GET) ---
    termo = request.args.get('q', '').strip()
    pagina = request.args.get('page', 1, type=int)
    itens_por_pagina = 50 

    where_sql = "WHERE p.ativo=1"
    params = []
    if termo:
        where_sql += " AND (p.nome LIKE ? OR p.gtin LIKE ? OR p.id_erp LIKE ?)"
        wildcard = f'%{termo}%'
        params = [wildcard, wildcard, wildcard]

    # Total de Itens
    total_itens = db.execute(f"SELECT COUNT(*) as total FROM produtos p {where_sql}", params).fetchone()['total']
    total_paginas = math.ceil(total_itens / itens_por_pagina)

    # Dados da Página
    offset = (pagina - 1) * itens_por_pagina
    sql_data = f'''
        SELECT p.id, p.nome, p.categoria, p.id_erp, p.gtin, p.preco_custo, p.preco_venda, p.id_unidade_padrao, p.ativo, u.sigla as unidade_padrao 
        FROM produtos p 
        LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id 
        {where_sql}
        ORDER BY p.nome 
        LIMIT ? OFFSET ?
    '''
    produtos = [dict(r) for r in db.execute(sql_data, params + [itens_por_pagina, offset]).fetchall()]
    
    # Unidades para o Modal
    unidades = [dict(r) for r in db.execute("SELECT * FROM unidades_medida ORDER BY sigla").fetchall()]
    
    return render_template('admin_produtos.html', 
                         produtos=produtos, unidades=unidades, 
                         busca=termo, pagina_atual=pagina, 
                         total_paginas=total_paginas, total_itens=total_itens,
                         is_gerente=True)

@app.route('/admin/produto/<int:prod_id>')
def admin_produto_json(prod_id):
    # 1. Adicionamos a Segurança (Só Gerente ou Chefe pode ver isso)
    if not session.get('is_gerente') and session.get('funcao') != 'Estoquista Chefe':
        return jsonify({'erro': 'Acesso negado'}), 403

    db = get_db()
    
    # 2. Buscamos o produto
    # O SELECT * funciona bem, desde que as colunas 'preco_custo' e 'preco_venda' 
    # existam na tabela 'produtos'.
    prod = db.execute("SELECT * FROM produtos WHERE id = ?", (prod_id,)).fetchone()
    
    if not prod:
        return jsonify({'erro': 'Produto não encontrado'}), 404

    # 3. Buscamos as unidades
    units = db.execute("SELECT * FROM produtos_unidades WHERE id_produto = ?", (prod_id,)).fetchall()
    
    # 4. Montamos a resposta
    dados = dict(prod)
    dados['unidades_permitidas'] = [dict(u) for u in units]
    
    return jsonify(dados)



@app.route('/excluir_item/<int:contagem_id>', methods=['POST'])
def excluir_item(contagem_id):
    # Verifica se tem usuário logado
    if not session.get('user_id'):
        return jsonify({'erro': 'Não autorizado'}), 401

    db = get_db()
    try:
        # Verifica se o inventário está aberto antes de deixar apagar
        item = db.execute('''
            SELECT c.id_inventario, i.status 
            FROM contagens c 
            JOIN inventarios i ON c.id_inventario = i.id 
            WHERE c.id = ?
        ''', (contagem_id,)).fetchone()

        if not item:
            return jsonify({'erro': 'Item não encontrado'}), 404
        
        if item['status'] != 'Aberto':
            return jsonify({'erro': 'Não é possível alterar um inventário fechado'}), 400

        # Executa a exclusão (Soft Delete não se aplica aqui pois é correção de erro imediata)
        db.execute('DELETE FROM contagens WHERE id = ?', (contagem_id,))
        db.commit()
        
        return jsonify({'sucesso': True})

    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500




# --- INTEGRAÇÃO ERP (CORRIGIDA E SEGURA) ---

@app.route('/admin/upload_erp', methods=['GET', 'POST'])
def upload_erp():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    if request.method == 'GET':
        return render_template('upload_erp.html', is_gerente=True)
        
    # PROCESSAMENTO DO ARQUIVO
    file = request.files.get('arquivo')
    if not file or not file.filename.endswith(('.xlsx', '.xls')):
        flash('Arquivo inválido', 'error')
        return redirect(url_for('upload_erp'))
        
    # Salva arquivo TEMPORÁRIO (Solução Definitiva para o erro de 4kb)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_import.xlsx')
    file.save(filepath)
    
    return redirect(url_for('analise_importacao'))


@app.route('/admin/analise_importacao')
def analise_importacao():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_import.xlsx')
    if not os.path.exists(filepath):
        flash('Envie o arquivo primeiro.', 'error')
        return redirect(url_for('upload_erp'))
        
    try:
        # Lê o Excel forçando a coluna ID_PRODUTO a ser lida como STRING (dtype=str)
        # Isso evita que o Pandas converta 1001 para 1001.0 automaticamente
        df = pd.read_excel(filepath, dtype={'ID_PRODUTO': str}).fillna('')
    except Exception as e:
        flash(f'Erro ao ler Excel: {e}', 'error')
        return redirect(url_for('upload_erp'))
        
    db = get_db()
    
    # --- ETAPA 1: Carregar IDs do Banco (Com Normalização Agressiva) ---
    print("\n--- INICIANDO DIAGNÓSTICO DE IMPORTAÇÃO ---")
    
    sql_existentes = "SELECT id_erp, nome, preco_venda, preco_custo, gtin, categoria, ativo FROM produtos WHERE id_erp IS NOT NULL"
    raw_db = db.execute(sql_existentes).fetchall()
    
    existentes_db = {}
    for r in raw_db:
        # Pega o ID bruto
        raw_id = r['id_erp']
        # Normaliza: Converte pra string -> remove espaços -> remove '.0' se existir
        clean_id = str(raw_id).strip().replace('.0', '')
        existentes_db[clean_id] = dict(r)
        
    # Debug: Mostra os 3 primeiros IDs que ele achou no banco
    print(f"DEBUG DB: Total carregados: {len(existentes_db)}")
    print(f"DEBUG DB: Exemplos de IDs no Banco: {list(existentes_db.keys())[:3]}")

    novos = []
    existentes = []
    
    # --- ETAPA 2: Processar Excel ---
    print("DEBUG EXCEL: Iniciando loop...")
    
    contador_debug = 0
    
    for _, row in df.iterrows():
        # Pega valor bruto do Excel
        raw_id_excel = row.get('ID_PRODUTO', '')
        
        # Normaliza EXATAMENTE da mesma forma que fizemos no banco
        id_erp = str(raw_id_excel).strip().replace('.0', '')
        
        if not id_erp or id_erp.lower() == 'nan': continue
        
        # --- BLOCO DE ESPIÃO (Vai imprimir os 5 primeiros casos para analisarmos) ---
        if contador_debug < 5:
            match = id_erp in existentes_db
            print(f"CHECK #{contador_debug}: Excel '{id_erp}' (Bruto: {raw_id_excel}) | Existe no Banco? {match}")
            if not match and contador_debug == 0:
                print(f"   -> ATENÇÃO: '{id_erp}' não foi encontrado nas chaves do banco.")
            contador_debug += 1
        # --------------------------------------------------------------------------

        # Dados do Excel
        nome_xl = str(row.get('PRODUTO', '')).strip()
        cat_xl = str(row.get('Contagem', '')).strip()
        gtin_xl = str(row.get('GTIN', '')).strip()
        if gtin_xl.endswith('.0'): gtin_xl = gtin_xl[:-2]
            
        custo_xl = float(row.get('CUSTO', 0) or 0)
        venda_xl = float(row.get('VALOR_VEND', 0) or 0)
        ativo_xl = 0 if str(row.get('STATUS', '')).strip().upper() == 'INATIVO' else 1

        if id_erp in existentes_db:
            prod_db = existentes_db[id_erp]
            
            nome_db = (prod_db['nome'] or '').strip()
            cat_db = (prod_db['categoria'] or '').strip()
            gtin_db = (prod_db['gtin'] or '').strip()
            custo_db = float(prod_db['preco_custo'] or 0)
            venda_db = float(prod_db['preco_venda'] or 0)
            ativo_db = int(prod_db['ativo'] if prod_db['ativo'] is not None else 1)
            
            # Diff Check
            tem_diferenca = False
            if nome_db != nome_xl: tem_diferenca = True
            if cat_db != cat_xl: tem_diferenca = True
            if gtin_db != gtin_xl: tem_diferenca = True
            if abs(custo_db - custo_xl) > 0.001: tem_diferenca = True
            if abs(venda_db - venda_xl) > 0.001: tem_diferenca = True
            if ativo_db != ativo_xl: tem_diferenca = True
            
            if tem_diferenca:
                existe = {
                    'id_erp': id_erp,
                    'nome': nome_db,
                    'nome_novo': nome_xl,
                    'custo_atual': custo_db,
                    'custo_novo': custo_xl,
                    'venda_atual': venda_db,
                    'venda_novo': venda_xl,
                    'gtin': gtin_xl,
                    'categoria': cat_xl,
                    'ativo': ativo_xl
                }
                existentes.append(existe)
        else:
            novo = {
                'id_erp': id_erp,
                'gtin': gtin_xl,
                'nome': nome_xl,
                'categoria': cat_xl,
                'und_str': str(row.get('UND', '')),
                'preco_custo': custo_xl,
                'preco_venda': venda_xl,
                'ativo': ativo_xl
            }
            novos.append(novo)
            
    print("--- FIM DO DIAGNÓSTICO ---\n")
    return render_template('analise_importacao.html', novos=novos, existentes=existentes, is_gerente=True)


@app.route('/admin/confirmar_importacao', methods=['POST'])
def confirmar_importacao():
    if not session.get('is_gerente'): return jsonify({'erro': 'Acesso negado'}), 403
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_import.xlsx')
    if not os.path.exists(filepath): return jsonify({'erro': 'Arquivo expirou'}), 400
    
    ids_selecionados = request.json.get('novos_ids', [])
    
    df = pd.read_excel(filepath).fillna('')
    db = get_db()
    unidades_map = {r['sigla'].upper(): r['id'] for r in db.execute("SELECT id, sigla FROM unidades_medida").fetchall()}
    
    count_novos, count_upd = 0, 0
    
    for _, row in df.iterrows():
        id_erp = str(row.get('ID_PRODUTO', '')).strip()
        if not id_erp: continue
        
        nome = str(row.get('PRODUTO', ''))
        gtin = str(row.get('GTIN', ''))
        categ = str(row.get('Contagem', ''))
        custo = float(row.get('CUSTO', 0) or 0)
        venda = float(row.get('VALOR_VEND', 0) or 0)
        ativo = 1 if str(row.get('STATUS', '')).upper() != 'INATIVO' else 0
        id_und = unidades_map.get(str(row.get('UND', '')).upper().strip(), 1)
        
        exists = db.execute("SELECT 1 FROM produtos WHERE id_erp = ?", (id_erp,)).fetchone()
        
        if exists:
            db.execute('''
                UPDATE produtos SET nome=?, gtin=?, categoria=?, preco_custo=?, preco_venda=?, ativo=?
                WHERE id_erp=?
            ''', (nome, gtin, categ, custo, venda, ativo, id_erp))
            count_upd += 1
        elif id_erp in ids_selecionados:
            db.execute('''
                INSERT INTO produtos (id_erp, gtin, nome, categoria, id_unidade_padrao, preco_custo, preco_venda, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (id_erp, gtin, nome, categ, id_und, custo, venda, ativo))
            
            novo_id = list(db.execute("SELECT last_insert_rowid()").fetchone())[0]
            db.execute("INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao) VALUES (?, ?, 1)", (novo_id, id_und))
            count_novos += 1
            
    db.commit()
    os.remove(filepath)
    
    return jsonify({'sucesso': True, 'msg': f'{count_novos} criados, {count_upd} atualizados.'})

# ============================================
# ROTAS ADMINISTRATIVAS (CRUDs) - QUE FALTAVAM
# ============================================

@app.route('/admin/unidades', methods=['GET', 'POST'])
def admin_unidades():
    if not session.get('is_gerente'):
        flash('Acesso negado.', 'error')
        return redirect(url_for('login_admin'))
    
    db = get_db()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'delete':
            unidade_id = request.form.get('unidade_id')
            # Verifica se está em uso antes de deletar (opcional, mas recomendado)
            db.execute('DELETE FROM unidades_medida WHERE id = ?', (unidade_id,))
            db.commit()
            flash('Unidade removida com sucesso!', 'success')
            
        else: # Save
            sigla = request.form.get('sigla', '').strip().upper()
            nome = request.form.get('nome', '').strip()
            permite_decimal = request.form.get('permite_decimal') == 'on'
            
            if sigla and nome:
                db.execute('INSERT INTO unidades_medida (sigla, nome, permite_decimal) VALUES (?, ?, ?)',
                           (sigla, nome, 1 if permite_decimal else 0))
                db.commit()
                flash('Unidade criada com sucesso!', 'success')
    
    # Listagem
    unidades = [dict(r) for r in db.execute("SELECT * FROM unidades_medida ORDER BY sigla").fetchall()]
    return render_template('admin_unidades.html', unidades=unidades, is_gerente=True)


@app.route('/admin/usuarios', methods=['GET', 'POST'])
def admin_usuarios():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()
    
    if request.method == 'POST':
        action = request.form.get('action')
        uid = request.form.get('usuario_id')
        
        if action == 'delete': # Soft Delete
            db.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (uid,))
            db.commit()
            flash('Usuário desativado.', 'success')
            
        elif action == 'save':
            nome = request.form.get('nome')
            funcao = request.form.get('funcao')
            senha = request.form.get('senha')
            ativo = 1 if request.form.get('ativo') == 'on' else 0
            
            if uid: # Update
                sql = "UPDATE usuarios SET nome=?, funcao=?, ativo=? WHERE id=?"
                params = [nome, funcao, ativo, uid]
                if senha: # Só atualiza senha se foi digitada
                    sql = "UPDATE usuarios SET nome=?, funcao=?, ativo=?, senha=? WHERE id=?"
                    params = [nome, funcao, ativo, senha, uid]
                db.execute(sql, params)
            else: # Insert
                db.execute("INSERT INTO usuarios (nome, funcao, senha, ativo) VALUES (?, ?, ?, ?)",
                           (nome, funcao, senha, ativo))
            db.commit()
            flash('Usuário salvo.', 'success')

    usuarios = [dict(r) for r in db.execute("SELECT * FROM usuarios ORDER BY nome").fetchall()]
    return render_template('admin_usuarios.html', usuarios=usuarios, is_gerente=True)


@app.route('/admin/setores', methods=['GET', 'POST'])
def admin_setores():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()
    
    if request.method == 'POST':
        action = request.form.get('action')
        sid = request.form.get('setor_id')
        
        if action == 'delete':
            # Verifica se há locais antes de deletar para evitar erro de integridade ou órfãos
            count = db.execute("SELECT COUNT(*) as t FROM locais WHERE id_setor=? AND ativo=1", (sid,)).fetchone()['t']
            if count > 0:
                flash(f'Não é possível excluir: existem {count} locais vinculados a este setor.', 'error')
            else:
                db.execute("UPDATE setores SET ativo=0 WHERE id=?", (sid,))
                db.commit()
                flash('Setor excluído.', 'success')

        elif action == 'save':
            nome = request.form.get('nome').strip()
            if not nome:
                flash('Nome é obrigatório.', 'error')
            else:
                if sid:
                    db.execute("UPDATE setores SET nome=? WHERE id=?", (nome, sid))
                else:
                    db.execute("INSERT INTO setores (nome) VALUES (?)", (nome,))
                db.commit()
                flash('Setor salvo com sucesso.', 'success')
            
    # --- A CORREÇÃO ESTÁ AQUI EMBAIXO ---
    # Antes estava apenas "SELECT * FROM setores". 
    # Agora fazemos a contagem cruzando com a tabela de locais.
    sql = '''
        SELECT s.*, COUNT(l.id) as total_locais 
        FROM setores s 
        LEFT JOIN locais l ON s.id = l.id_setor AND l.ativo=1
        WHERE s.ativo=1
        GROUP BY s.id 
        ORDER BY s.nome
    '''
    setores = [dict(r) for r in db.execute(sql).fetchall()]
    
    return render_template('admin_setores.html', setores=setores, is_gerente=True)

@app.route('/admin/locais', methods=['GET', 'POST'])
def admin_locais():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    db = get_db()
    
    if request.method == 'POST':
        action = request.form.get('action')
        lid = request.form.get('local_id')
        
        if action == 'delete':
            db.execute("UPDATE locais SET ativo=0 WHERE id=?", (lid,))
            db.commit()
        elif action == 'save':
            nome = request.form.get('nome')
            setor = request.form.get('id_setor')
            if lid:
                db.execute("UPDATE locais SET nome=?, id_setor=? WHERE id=?", (nome, setor, lid))
            else:
                db.execute("INSERT INTO locais (nome, id_setor, status) VALUES (?, ?, 0)", (nome, setor))
            db.commit()
            
    locais = [dict(r) for r in db.execute("SELECT l.*, s.nome as setor_nome FROM locais l JOIN setores s ON l.id_setor=s.id WHERE l.ativo=1 AND s.ativo=1 ORDER BY s.nome, l.nome").fetchall()]
    setores = [dict(r) for r in db.execute("SELECT * FROM setores WHERE ativo=1 ORDER BY nome").fetchall()]
    return render_template('admin_locais.html', locais=locais, setores=setores, is_gerente=True)


# ====================================================================================
# ROTAS DE GESTÃO DE OCORRÊNCIAS (V1 - PAINEL GERENTE)
# ====================================================================================

@app.route('/admin/ocorrencias')
def admin_ocorrencias():
    if not session.get('is_gerente'): return redirect(url_for('login_admin'))
    
    db = get_db()
    
    # 1. Busca ocorrências (com conversão para Dict)
    sql_ocorrencias = '''
        SELECT o.*, l.nome as local_nome, u.sigla as unidade_sigla
        FROM ocorrencias o
        JOIN locais l ON o.id_local = l.id
        LEFT JOIN unidades_medida u ON o.id_unidade = u.id
        WHERE o.resolvido = 0
        ORDER BY o.data_hora DESC
    '''
    rows_ocorrencias = db.execute(sql_ocorrencias).fetchall()
    ocorrencias = [dict(row) for row in rows_ocorrencias]
    
    # 2. Busca produtos (para o vínculo)
    rows_produtos = db.execute("SELECT id, nome FROM produtos WHERE ativo = 1 ORDER BY nome").fetchall()
    produtos = [dict(row) for row in rows_produtos]

    # 3. CORREÇÃO DO FORMULÁRIO: Busca Unidades
    rows_unidades = db.execute("SELECT * FROM unidades_medida ORDER BY id").fetchall()
    unidades = [dict(row) for row in rows_unidades]
    
    return render_template('ocorrencias.html', 
                         ocorrencias=ocorrencias, 
                         produtos=produtos,
                         unidades=unidades, # <--- ISSO CONSERTA O FORMULÁRIO DE CADASTRO
                         is_gerente=True)


@app.route('/api/registrar_ocorrencia', methods=['POST'])
def registrar_ocorrencia():
    # ... (código de verificação de permissão, se houver) ...
    
    try:
        nome = request.form.get('nome')
        quantidade = request.form.get('quantidade')
        unidade_id = request.form.get('unidade_id')
        local_id = request.form.get('local_id')
        foto = request.files.get('foto')
        
        path_db = None
        
        if foto and foto.filename:
            # Garante a pasta
            upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'ocorrencias')
            os.makedirs(upload_folder, exist_ok=True)
            
            # Gera nome seguro e único
            filename = f"{uuid.uuid4().hex}_{secure_filename(foto.filename)}"
            full_path = os.path.join(upload_folder, filename)
            foto.save(full_path)
            
            # CORREÇÃO DA IMAGEM: Salva apenas o caminho relativo com barras normais (/)
            # Ex: uploads/ocorrencias/minhafoto.jpg
            path_db = f"uploads/ocorrencias/{filename}"
            
        db = get_db()
        db.execute('''
            INSERT INTO ocorrencias (id_inventario, id_local, nome_identificado, quantidade, id_unidade, foto_path, data_hora, resolvido)
            VALUES ((SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1), ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0)
        ''', (local_id, nome, quantidade, unidade_id, path_db))
        db.commit()
        
        return jsonify({'sucesso': True})
        
    except Exception as e:
        print(f"Erro ocorrência: {e}")
        return jsonify({'erro': str(e)}), 500



@app.route('/api/vincular_ocorrencia', methods=['POST'])
def vincular_ocorrencia():
    if not session.get('is_gerente'): 
        return jsonify({'erro': 'Acesso negado'}), 403
    
    data = request.json
    id_ocorrencia = data.get('id_ocorrencia')
    id_produto_destino = data.get('id_produto_destino')
    
    db = get_db()
    
    # 1. Busca dados da ocorrência original
    ocorrencia = db.execute('SELECT * FROM ocorrencias WHERE id = ?', (id_ocorrencia,)).fetchone()
    if not ocorrencia:
        return jsonify({'erro': 'Ocorrência não encontrada'}), 404
        
    try:
        # 2. Insere na tabela contagens (CORREÇÃO: Adicionado id_usuario)
        # Estamos usando o ID do gerente logado, pois ele validou a operação
        db.execute('''
            INSERT INTO contagens 
            (id_inventario, id_local, id_produto, quantidade, id_unidade_usada, id_usuario, data_hora)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            ocorrencia['id_inventario'], 
            ocorrencia['id_local'], 
            id_produto_destino, 
            ocorrencia['quantidade'], 
            ocorrencia['id_unidade'],
            session.get('user_id')  # <--- AQUI ESTAVA FALTANDO
        ))
        
        # 3. Marca ocorrência como resolvida
        db.execute('''
            UPDATE ocorrencias 
            SET resolvido = 1, obs = ? 
            WHERE id = ?
        ''', (f'Vinculado ao Produto ID {id_produto_destino}', id_ocorrencia))
        
        db.commit()
        return jsonify({'sucesso': True})
        
    except Exception as e:
        db.rollback()
        print(f"Erro ao vincular: {e}")
        return jsonify({'erro': str(e)}), 500

@app.route('/api/cadastrar_da_ocorrencia', methods=['POST'])
def cadastrar_da_ocorrencia():
    if not session.get('is_gerente'): 
        return jsonify({'erro': 'Acesso negado'}), 403
        
    # Como estamos recebendo FormData (arquivo + campos), usamos request.form
    # Nota: Se o form de produto vier como JSON, ajuste para request.json. 
    # Mas geralmente forms de cadastro vem como form-data.
    
    # Vamos assumir que você adaptou o modal de produto para enviar JSON ou Form
    # Aqui vou usar uma lógica híbrida segura:
    dados = request.form if request.form else request.json
    
    id_ocorrencia = dados.get('id_ocorrencia')
    
    db = get_db()
    ocorrencia = db.execute('SELECT * FROM ocorrencias WHERE id = ?', (id_ocorrencia,)).fetchone()
    if not ocorrencia:
        return jsonify({'erro': 'Ocorrência não encontrada'}), 404
    try:
        # 1. Cria o Novo Produto (Exemplo simplificado - ajuste aos campos do seu form)
        cur = db.cursor()
        cur.execute('''
            INSERT INTO produtos (nome, id_erp, gtin, categoria, preco_custo, id_unidade_padrao, ativo)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (
            dados.get('nome'),
            dados.get('id_erp'),
            dados.get('gtin'),
            dados.get('categoria'),
            dados.get('preco_custo') or 0,
            dados.get('id_unidade_padrao')
        ))
        novo_prod_id = cur.lastrowid
        
        # 3. Insere a Contagem (CORREÇÃO: Adicionado id_usuario)
        db.execute('''
            INSERT INTO contagens 
            (id_inventario, id_local, id_produto, quantidade, id_unidade_usada, id_usuario, data_hora)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            ocorrencia['id_inventario'], 
            ocorrencia['id_local'], 
            novo_prod_id, 
            ocorrencia['quantidade'], 
            ocorrencia['id_unidade'],
            session.get('user_id') # <--- AQUI ESTAVA FALTANDO
        ))

        # 4. Resolve Ocorrência
        db.execute('UPDATE ocorrencias SET resolvido = 1, obs = ? WHERE id = ?', 
                  (f'Gerado novo produto ID {novo_prod_id}', id_ocorrencia))
        
        db.commit()
        return jsonify({'sucesso': True})
        
    except Exception as e:
        db.rollback()
        print(f"Erro ao cadastrar da ocorrência: {e}")
        return jsonify({'erro': str(e)}), 500


@app.route('/api/rejeitar_ocorrencia/<int:id_ocorrencia>', methods=['POST'])
def api_rejeitar_ocorrencia(id_ocorrencia):
    """Rejeita uma ocorrência (marca como resolvida sem gerar estoque).
    """
    if 'user_id' not in session:
        return jsonify({'sucesso': False, 'error': 'Login necessário'}), 401
    
    db = get_db()
    
    try:
        # Apenas marca como resolvida (rejeitado pelo gerente)
        db.execute("UPDATE ocorrencias SET resolvido=1 WHERE id=?", (id_ocorrencia,))
        db.commit()
        return jsonify({'sucesso': True, 'message': 'Ocorrência rejeitada'}), 200
    
    except Exception as e:
        db.rollback()
        return jsonify({'sucesso': False, 'error': str(e)}), 500


# --- HANDLERS DE ERRO GLOBAIS ---
@app.errorhandler(404)
def pagina_nao_encontrada(error):
    return render_template('erro_404.html'), 404


@app.errorhandler(500)
def erro_interno(error):
    return render_template('erro_500.html', erro=str(error)), 500


# Coloque isso no final do app.py, antes do app.run()

@app.errorhandler(Exception)
def handle_exception(e):
    # Passa erros HTTP normais (como 404) direto
    if hasattr(e, "code"):
        return e
    
    # Se for erro de código (500), imprime no terminal
    print("\n🚨 ERRO NÃO TRATADO NO SERVIDOR 🚨")
    traceback.print_exc()
    print("\n")
    
    return jsonify({'erro': 'Erro interno do servidor', 'detalhes': str(e)}), 500


# ==========================================
# ROTAS DE RELATÓRIOS E EXCEL
# ==========================================

import openpyxl
from openpyxl.styles import Font, Alignment
from io import BytesIO
from flask import send_file


@app.route('/historico')
def historico():
    if not session.get('is_gerente'):
        return redirect(url_for('login_admin'))
    
    db = get_db()
    
    sql = '''
        SELECT 
            i.id, 
            i.data_criacao,
            i.data_fechamento, 
            i.status, 
            i.descricao,
            (SELECT SUM(c.quantidade_padrao * c.preco_custo_snapshot) 
             FROM contagens c 
             JOIN produtos p ON c.id_produto = p.id 
             WHERE c.id_inventario = i.id) as valor_total
        FROM inventarios i
        WHERE i.status = 'Fechado'
        ORDER BY i.data_fechamento DESC -- Ordenamos pela data real de término
    '''
    
    inventarios = db.execute(sql).fetchall()
    
    return render_template('historico.html', inventarios=[dict(i) for i in inventarios])

@app.route('/exportar_excel/<int:inventario_id>')
def exportar_excel(inventario_id):
    if not session.get('is_gerente'):
        return redirect(url_for('login_admin'))
        
    db = get_db()
    
    # 1. Busca dados do inventário
    inv = db.execute("SELECT * FROM inventarios WHERE id = ?", (inventario_id,)).fetchone()
    if not inv: return "Inventário não encontrado", 404
    
    # 2. Busca todas as contagens detalhadas (USANDO DADOS SNAPSHOT DA CONTAGEM)
    # Nota: Usamos COALESCE para garantir que não quebre se tiver algum dado antigo sem snapshot
    sql = '''
        SELECT 
            p.id_erp, 
            p.gtin, 
            p.nome as produto, 
            p.categoria,
            
            -- Dados da Contagem (O que foi digitado)
            c.quantidade as qtd_informada, 
            u.sigla as unidade_informada,
            
            -- Dados de Auditoria/Conversão (Snapshot)
            c.fator_conversao,
            c.quantidade_padrao,
            c.unidade_padrao_sigla,
            
            -- Dados Financeiros (Snapshot do momento da contagem)
            c.preco_custo_snapshot,
            (c.quantidade_padrao * c.preco_custo_snapshot) as valor_total_linha,
            
            -- Metadados
            l.nome as local, 
            s.nome as setor,
            usu.nome as contado_por,
            c.data_hora
            
        FROM contagens c
        JOIN produtos p ON c.id_produto = p.id
        JOIN locais l ON c.id_local = l.id
        JOIN setores s ON l.id_setor = s.id
        JOIN unidades_medida u ON c.id_unidade_usada = u.id
        LEFT JOIN usuarios usu ON c.id_usuario = usu.id
        WHERE c.id_inventario = ?
        ORDER BY s.nome, l.nome, p.nome
    '''
    itens = db.execute(sql, (inventario_id,)).fetchall()
    
    # 3. Gera o Excel na memória
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Inventario_{inventario_id}"
    
    # Cabeçalho Expandido
    headers = [
        "ID ERP", "GTIN", "Produto", "Categoria", 
        "Qtd Informada", "Und Inf.", "Fator Conv.",     # Bloco da Contagem
        "Qtd Padrão", "Und Padrão",                     # Bloco da Conversão
        "Custo Unit. (Snapshot)", "Valor Total (R$)",   # Bloco Financeiro
        "Local", "Setor", "Usuário", "Data/Hora"        # Bloco Rastreabilidade
    ]
    ws.append(headers)
    
    # Estiliza cabeçalho (Negrito)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    
    # Preenche dados
    for item in itens:
        # Formatação básica da data para ficar limpa
        data_limpa = item['data_hora'][:19].replace('T', ' ') if item['data_hora'] else ''
        
        ws.append([
            item['id_erp'],
            item['gtin'], 
            item['produto'], 
            item['categoria'],
            
            item['qtd_informada'], 
            item['unidade_informada'], 
            item['fator_conversao'],
            
            item['quantidade_padrao'], 
            item['unidade_padrao_sigla'],
            
            item['preco_custo_snapshot'],
            item['valor_total_linha'],
            
            item['local'], 
            item['setor'],
            item['contado_por'], 
            data_limpa
        ])
        
    # Ajusta largura das colunas principais
    ws.column_dimensions['C'].width = 40 # Produto
    ws.column_dimensions['H'].width = 15 # Qtd Padrão
    ws.column_dimensions['K'].width = 15 # Valor Total
    
    # Salva em memória (BytesIO)
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    nome_arquivo = f"Inventario_{inv['data_criacao'][:10]}_{inventario_id}.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=nome_arquivo
    )


@app.route('/api/heartbeat')
def heartbeat():
    try:
        db = get_db()
        inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
        
        if not inv:
            return jsonify({'ativo': False})
        
        # 1. Contagens
        qtd_contagens = db.execute("SELECT COUNT(*) FROM contagens WHERE id_inventario = ?", (inv['id'],)).fetchone()[0]
        
        # 2. Ocorrências
        qtd_ocorrencias = db.execute("SELECT COUNT(*) FROM ocorrencias WHERE id_inventario = ?", (inv['id'],)).fetchone()[0]
        
        # 3. Locais Finalizados (Aqui está o suspeito)
        # Vamos contar de forma insensível a maiúsculas/minúsculas para garantir
        qtd_locais_finalizados = db.execute("SELECT COUNT(*) FROM locais WHERE status = 2").fetchone()[0]
        
        # Soma
        versao_dados = qtd_contagens + qtd_ocorrencias + qtd_locais_finalizados
        
        
        return jsonify({
            'ativo': True,
            'versao': versao_dados
        })
    except Exception as e:
        print(f"Erro no heartbeat: {e}")
        return jsonify({'ativo': False})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)