import csv
import io
import math
import os
import traceback
import uuid
import pandas as pd
from datetime import date, datetime
import sqlite3
from flask import Blueprint, render_template, redirect, url_for, request, session, flash, jsonify, send_file, current_app
from werkzeug.utils import secure_filename
from ..db import get_db
from ..utils import get_local_ip, registrar_movimento
from dotenv import load_dotenv

bp = Blueprint('admin', __name__, url_prefix='/admin')


# Helpers

def gerente_required():
    return session.get('is_gerente')


@bp.route('/dashboard')
def dashboard():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status = 'Aberto' LIMIT 1").fetchone()
    inventario_aberto = dict(inv) if inv else None

    # Buscar categorias para o modal de abertura de inventário
    categorias = []
    if not inventario_aberto:
        sql_categorias = '''
            SELECT 
                c.id,
                c.nome,
                COUNT(pc.id_produto) as total_produtos
            FROM categorias_inventario c
            LEFT JOIN produto_categoria_inventario pc ON c.id = pc.id_categoria
            WHERE c.ativo = 1
            GROUP BY c.id
            ORDER BY c.nome
        '''
        categorias = [dict(r) for r in db.execute(sql_categorias).fetchall()]

    kpis = {'total_locais': 0, 'locais_concluidos': 0, 'percentual': 0, 'valor_total_estoque': 0.0}
    relatorio, progresso, logs, nao_contados = [], [], [], []

    if inventario_aberto:
        inv_id = inventario_aberto['id']

        total_loc = db.execute('SELECT COUNT(*) as t FROM locais').fetchone()['t']
        concluidos = db.execute('SELECT COUNT(*) as t FROM locais WHERE status = 2').fetchone()['t']
        kpis['total_locais'] = total_loc
        kpis['locais_concluidos'] = concluidos
        kpis['percentual'] = round((concluidos/total_loc*100), 1) if total_loc > 0 else 0

        sql_financeiro = '''
            SELECT SUM(c.quantidade * COALESCE(pu.fator_conversao, 1.0) * COALESCE(p.preco_custo, 0)) as total_reais
            FROM contagens c
            JOIN produtos p ON c.id_produto = p.id
            LEFT JOIN produtos_unidades pu ON p.id = pu.id_produto AND c.id_unidade_usada = pu.id_unidade
            WHERE c.id_inventario = ?
        '''
        resultado_fin = db.execute(sql_financeiro, (inv_id,)).fetchone()
        valor_calculado = resultado_fin['total_reais'] if resultado_fin and resultado_fin['total_reais'] else 0.0
        kpis['valor_total_estoque'] = valor_calculado

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
            row['percentual'] = round((row['concluidos'] / row['total_locais'] * 100), 1) if row['total_locais'] > 0 else 0
            progresso.append(row)

        logs = [dict(r) for r in db.execute('SELECT * FROM logs_auditoria ORDER BY id DESC LIMIT 10').fetchall()]

        # Pendências filtra por categoria se inventário for PARCIAL
        if inventario_aberto['tipo_inventario'] == 'PARCIAL' and inventario_aberto['id_categoria_escopo']:
            sql_nao = '''
                SELECT COUNT(*) as total 
                FROM produtos p 
                JOIN produto_categoria_inventario pc ON p.id = pc.id_produto
                LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ? 
                WHERE c.id IS NULL 
                AND p.ativo = 1
                AND pc.id_categoria = ?
            '''
            total_pendencias = db.execute(sql_nao, (inv_id, inventario_aberto['id_categoria_escopo'])).fetchone()['total']
        else:
            sql_nao = '''
                SELECT COUNT(*) as total FROM produtos p 
                LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ? 
                WHERE c.id IS NULL AND p.ativo = 1
            '''
            total_pendencias = db.execute(sql_nao, (inv_id,)).fetchone()['total']
        
        nao_contados = total_pendencias

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
                    'produto_id': pid,
                    'nome': r['nome'],
                    'padrao': r['padrao_sigla'],
                    'soma_por_unidade': {},
                    'total_consolidado': 0.0,
                    'preco_custo': r['preco_custo'] or 0
                }

            if sigla not in temp_rel[pid]['soma_por_unidade']:
                temp_rel[pid]['soma_por_unidade'][sigla] = 0
            temp_rel[pid]['soma_por_unidade'][sigla] += qtd
            temp_rel[pid]['total_consolidado'] += (qtd * r['fator'])

        for pid, dados in temp_rel.items():
            partes = []
            for sigla, total_unid in dados['soma_por_unidade'].items():
                qtd_fmt = int(total_unid) if total_unid.is_integer() else total_unid
                partes.append(f"{qtd_fmt} {sigla}")

            resumo_detalhes = ", ".join(partes)
            relatorio.append({
                'produto_id': dados['produto_id'],
                'produto_nome': dados['nome'],
                'detalhamento': resumo_detalhes,
                'total_final': round(dados['total_consolidado'], 2),
                'unidade_padrao': dados['padrao'],
                'valor_total': round(dados['total_consolidado'] * dados['preco_custo'], 2)
            })

    ocorrencias_pendentes = 0
    if inventario_aberto:
        inv_id = inventario_aberto['id']
        result = db.execute(
            "SELECT COUNT(*) as count FROM ocorrencias WHERE id_inventario = ? AND resolvido = 0",
            (inv_id,)
        ).fetchone()
        ocorrencias_pendentes = result['count'] if result else 0

    # Contar lotes pendentes de aprovação
    lotes_pendentes_count = 0
    result_lotes = db.execute(
        "SELECT COUNT(*) as count FROM lotes_movimentacao WHERE status = 'PENDENTE_APROVACAO'"
    ).fetchone()
    lotes_pendentes_count = result_lotes['count'] if result_lotes else 0

    return render_template(
        'admin/dashboard.html',
        inventario_aberto=inventario_aberto,
        kpis=kpis,
        relatorio=relatorio,
        progresso_setores=progresso,
        logs_recentes=logs,
        total_pendencias=nao_contados if inventario_aberto else 0,
        ocorrencias_pendentes=ocorrencias_pendentes,
        lotes_pendentes_count=lotes_pendentes_count,
        categorias=categorias,
        is_gerente=True
    )


@bp.route('/gerar_qrcode')
def gerar_qrcode():
    
    load_dotenv()
    perfil = os.getenv('PERFIL_MAQUINA', 'LOJA').strip().upper()
    
    ip = get_local_ip()
    # LOJA: QR Code aponta para contagem (seleção de usuário)
    # GERENTE/CADASTRO: QR Code aponta para área administrativa
    if perfil == 'LOJA':
        url = f"http://{ip}:5000"
    else:
        url = f"http://{ip}:5000/login_admin"
    
    try:
        import qrcode
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png', download_name='qrcode.png')
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@bp.route('/get_url_servidor')
def get_url_servidor():
    """Retorna a URL do servidor para ser exibida no modal QR Code."""
    from dotenv import load_dotenv
    load_dotenv()
    perfil = os.getenv('PERFIL_MAQUINA', 'LOJA').strip().upper()
    
    ip = get_local_ip()
    # LOJA: URL para contagem | GERENTE/CADASTRO: URL para admin
    if perfil == 'LOJA':
        url = f"http://{ip}:5000"
    else:
        url = f"http://{ip}:5000/login_admin"
    
    return jsonify({'url': url})


@bp.route('/monitoramento')
def monitoramento():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status = 'Aberto' LIMIT 1").fetchone()
    inventario_aberto = dict(inv) if inv else None

    progresso_setores, relatorio = [], []

    if inventario_aberto:
        inv_id = inventario_aberto['id']

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
                    'soma_por_unidade': defaultdict(float),
                    'total_std': 0.0,
                    'total_valor': 0.0
                }
            fator = float(r['fator']) if r['fator'] else 1.0
            qtd_convertida = r['quantidade'] * fator
            temp_rel[pid]['soma_por_unidade'][r['unit_sigla']] += r['quantidade']
            temp_rel[pid]['total_std'] += qtd_convertida
            temp_rel[pid]['total_valor'] += qtd_convertida * temp_rel[pid]['preco_custo']

        for pid, dados in temp_rel.items():
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

        sql_count_pendencias = '''
            SELECT COUNT(*) as total FROM produtos p
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            WHERE c.id IS NULL AND p.ativo = 1
        '''
        total_pendencias = db.execute(sql_count_pendencias, (inv_id,)).fetchone()['total']
    else:
        total_pendencias = 0

    return render_template(
        'admin/monitoramento.html',
        inventario_aberto=inventario_aberto,
        progresso_setores=progresso_setores,
        relatorio=relatorio,
        total_pendencias=total_pendencias,
        is_gerente=True
    )


@bp.route('/monitoramento/pendencias')
def monitoramento_pendencias():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        return redirect(url_for('admin.dashboard'))

    inv_id = inv['id']
    inv_dict = dict(inv)
    
    pagina = request.args.get('page', 1, type=int)
    itens_por_pagina = 50
    offset = (pagina - 1) * itens_por_pagina

    # Filtrar por categoria se inventário for PARCIAL
    if inv_dict['tipo_inventario'] == 'PARCIAL' and inv_dict['id_categoria_escopo']:
        sql_pendencias = '''
            SELECT p.id, p.nome, p.categoria, p.preco_custo
            FROM produtos p
            JOIN produto_categoria_inventario pc ON p.id = pc.id_produto
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            WHERE c.id IS NULL 
            AND p.ativo = 1
            AND pc.id_categoria = ?
            ORDER BY p.nome
            LIMIT ? OFFSET ?
        '''
        pendencias = [dict(r) for r in db.execute(sql_pendencias, (inv_id, inv_dict['id_categoria_escopo'], itens_por_pagina, offset)).fetchall()]

        sql_count = '''
            SELECT COUNT(*) as total FROM produtos p
            JOIN produto_categoria_inventario pc ON p.id = pc.id_produto
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            WHERE c.id IS NULL 
            AND p.ativo = 1
            AND pc.id_categoria = ?
        '''
        total = db.execute(sql_count, (inv_id, inv_dict['id_categoria_escopo'])).fetchone()['total']
    else:
        sql_pendencias = '''
            SELECT p.id, p.nome, p.categoria, p.preco_custo
            FROM produtos p
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            WHERE c.id IS NULL AND p.ativo = 1
            ORDER BY p.nome
            LIMIT ? OFFSET ?
        '''
        pendencias = [dict(r) for r in db.execute(sql_pendencias, (inv_id, itens_por_pagina, offset)).fetchall()]

        sql_count = '''
            SELECT COUNT(*) as total FROM produtos p
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            WHERE c.id IS NULL AND p.ativo = 1
        '''
        total = db.execute(sql_count, (inv_id,)).fetchone()['total']
    
    total_paginas = (total + itens_por_pagina - 1) // itens_por_pagina

    return render_template(
        'admin/monitoramento_pendencias.html',
        pendencias=pendencias,
        pagina_atual=pagina,
        total_paginas=total_paginas,
        total_pendencias=total,
        is_gerente=True
    )


@bp.route('/monitoramento/setor/<int:setor_id>')
def monitoramento_setor(setor_id):
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    db = get_db()
    setor = db.execute("SELECT * FROM setores WHERE id = ?", (setor_id,)).fetchone()
    if not setor:
        return redirect(url_for('admin.monitoramento'))

    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        return redirect(url_for('admin.dashboard'))

    inv_id = inv['id']

    sql_locais = '''
        SELECT l.*, COALESCE(COUNT(c.id), 0) as qtd_contagens
        FROM locais l
        LEFT JOIN contagens c ON l.id = c.id_local AND c.id_inventario = ?
        WHERE l.id_setor = ?
        GROUP BY l.id ORDER BY l.nome
    '''
    locais = [dict(r) for r in db.execute(sql_locais, (inv_id, setor_id)).fetchall()]

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

    return render_template(
        'admin/monitoramento_setor.html',
        setor=dict(setor),
        locais=locais,
        itens=itens,
        is_gerente=True
    )


@bp.route('/monitoramento/produto/<int:produto_id>')
def detalhe_produto_inventario(produto_id):
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        return redirect(url_for('admin.dashboard'))

    inv_id = inv['id']
    produto = db.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    if not produto:
        return redirect(url_for('admin.monitoramento'))

    sql_resumo = '''
        SELECT 
            COALESCE(SUM(c.quantidade * COALESCE(pu.fator_conversao, 1.0)), 0.0) as total_padrao,
            COALESCE(SUM(c.quantidade * COALESCE(pu.fator_conversao, 1.0) * ?), 0.0) as valor_total
        FROM contagens c
        LEFT JOIN produtos_unidades pu ON c.id_produto = pu.id_produto AND c.id_unidade_usada = pu.id_unidade
        WHERE c.id_produto = ? AND c.id_inventario = ?
    '''
    resumo = db.execute(sql_resumo, (float(produto['preco_custo'] or 0.0), produto_id, inv_id)).fetchone()

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

    return render_template(
        'admin/detalhe_produto.html',
        produto=dict(produto),
        resumo=dict(resumo),
        detalhes=detalhes,
        is_gerente=True
    )


# Ações de inventário


@bp.route('/abrir_inventario', methods=['POST'])
def abrir_inventario():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    if not db.execute("SELECT id FROM inventarios WHERE status='Aberto'").fetchone():
        tipo_inventario = request.form.get('tipo_inventario', 'COMPLETO')
        id_categoria = request.form.get('id_categoria')
        
        # Validações
        if tipo_inventario == 'PARCIAL' and not id_categoria:
            flash('❌ Selecione uma categoria para inventário parcial.', 'error')
            return redirect(url_for('admin.dashboard'))
        
        # Buscar nome da categoria para descrição
        descricao = 'Inventário COMPLETO - Iniciado pelo Gerente'
        
        if tipo_inventario == 'PARCIAL' and id_categoria:
            categoria = db.execute(
                'SELECT nome FROM categorias_inventario WHERE id = ?',
                (id_categoria,)
            ).fetchone()
            
            if not categoria:
                flash('❌ Categoria não encontrada.', 'error')
                return redirect(url_for('admin.dashboard'))
            
            descricao = f'Inventário PARCIAL - Categoria: {categoria["nome"]} - Iniciado pelo Gerente'
            
            db.execute('''
                INSERT INTO inventarios (data_criacao, status, descricao, tipo_inventario, id_categoria_escopo)
                VALUES (?, ?, ?, ?, ?)
            ''', (date.today().isoformat(), 'Aberto', descricao, tipo_inventario, id_categoria))
        else:
            # Para inventário COMPLETO, usar categoria GERAL
            categoria_geral = db.execute(
                'SELECT id FROM categorias_inventario WHERE nome = ?',
                ('GERAL',)
            ).fetchone()
            
            db.execute('''
                INSERT INTO inventarios (data_criacao, status, descricao, tipo_inventario, id_categoria_escopo)
                VALUES (?, ?, ?, ?, ?)
            ''', (date.today().isoformat(), 'Aberto', descricao, tipo_inventario, categoria_geral['id'] if categoria_geral else None))
        
        db.commit()
        
        tipo_msg = 'completo' if tipo_inventario == 'COMPLETO' else 'parcial'
        flash(f'✅ Inventário {tipo_msg} iniciado com sucesso!', 'success')
    
    return redirect(url_for('admin.dashboard'))


@bp.route('/preview_fechamento')
def preview_fechamento():
    """Tela de preview/revisão antes de fechar o inventário."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        flash('Nenhum inventário aberto.', 'error')
        return redirect(url_for('admin.dashboard'))
    
    inv_id = inv['id']
    inv_dict = dict(inv)
    
    # Verificar ocorrências pendentes
    ocorrencias_pendentes = db.execute(
        "SELECT COUNT(*) as count FROM ocorrencias WHERE id_inventario = ? AND resolvido = 0",
        (inv_id,)
    ).fetchone()
    
    if ocorrencias_pendentes['count'] > 0:
        flash(f"❌ Existem {ocorrencias_pendentes['count']} ocorrências pendentes! Resolva todas antes de fechar.", 'error')
        return redirect(url_for('admin.admin_ocorrencias'))
    
    # Determinar escopo dos produtos (COMPLETO ou PARCIAL)
    if inv_dict['tipo_inventario'] == 'PARCIAL' and inv_dict['id_categoria_escopo']:
        # Inventário PARCIAL: apenas produtos da categoria
        sql_produtos = '''
            SELECT 
                p.id as produto_id,
                p.nome as produto_nome,
                p.id_erp,
                p.gtin,
                COALESCE(
                    (SELECT SUM(saldo) FROM estoque_saldos WHERE produto_id = p.id),
                    0
                ) as estoque_atual,
                p.preco_custo,
                COALESCE(SUM(c.quantidade_padrao), 0) as quantidade_contada,
                u.sigla as unidade_padrao,
                COUNT(c.id) as total_contagens
            FROM produtos p
            JOIN produto_categoria_inventario pc ON p.id = pc.id_produto
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.ativo = 1 
            AND p.controla_estoque = 1
            AND pc.id_categoria = ?
            GROUP BY p.id
            ORDER BY p.nome
        '''
        produtos = db.execute(sql_produtos, (inv_id, inv_dict['id_categoria_escopo'])).fetchall()
        
        # Buscar nome da categoria
        categoria = db.execute(
            "SELECT nome FROM categorias_inventario WHERE id = ?",
            (inv_dict['id_categoria_escopo'],)
        ).fetchone()
        nome_categoria = categoria['nome'] if categoria else 'Categoria'
    else:
        # Inventário COMPLETO: todos os produtos ativos
        sql_produtos = '''
            SELECT 
                p.id as produto_id,
                p.nome as produto_nome,
                p.id_erp,
                p.gtin,
                COALESCE(
                    (SELECT SUM(saldo) FROM estoque_saldos WHERE produto_id = p.id),
                    0
                ) as estoque_atual,
                p.preco_custo,
                COALESCE(SUM(c.quantidade_padrao), 0) as quantidade_contada,
                u.sigla as unidade_padrao,
                COUNT(c.id) as total_contagens
            FROM produtos p
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.ativo = 1 AND p.controla_estoque = 1
            GROUP BY p.id
            ORDER BY p.nome
        '''
        produtos = db.execute(sql_produtos, (inv_id,)).fetchall()
        nome_categoria = None
    
    # Processar divergências e calcular totalizadores
    comparacao = []
    total_produtos = 0
    total_divergencias = 0
    total_entradas = 0
    total_saidas = 0
    total_ok = 0
    total_nao_contados = 0
    valor_total_ajustes = 0.0
    
    for produto in produtos:
        estoque_sistema = float(produto['estoque_atual'] or 0)
        quantidade_contada = float(produto['quantidade_contada'] or 0)
        diferenca = quantidade_contada - estoque_sistema
        preco_custo = float(produto['preco_custo'] or 0)
        valor_ajuste = abs(diferenca) * preco_custo
        foi_contado = produto['total_contagens'] > 0
        
        # Determinar tipo de ajuste
        if abs(diferenca) < 0.001:
            tipo_ajuste = 'OK'
            icone_ajuste = '✅'
            cor_ajuste = 'emerald'
            total_ok += 1
        elif diferenca > 0:
            tipo_ajuste = 'ENTRADA'
            icone_ajuste = '📈'
            cor_ajuste = 'blue'
            total_entradas += 1
            total_divergencias += 1
            valor_total_ajustes += valor_ajuste
        else:
            tipo_ajuste = 'SAIDA'
            icone_ajuste = '📉'
            cor_ajuste = 'red'
            total_saidas += 1
            total_divergencias += 1
            valor_total_ajustes += valor_ajuste
        
        if not foi_contado:
            total_nao_contados += 1
        
        comparacao.append({
            'produto_id': produto['produto_id'],
            'produto_nome': produto['produto_nome'],
            'id_erp': produto['id_erp'],
            'gtin': produto['gtin'],
            'estoque_sistema': estoque_sistema,
            'quantidade_contada': quantidade_contada,
            'diferenca': diferenca,
            'tipo_ajuste': tipo_ajuste,
            'icone_ajuste': icone_ajuste,
            'cor_ajuste': cor_ajuste,
            'preco_custo': preco_custo,
            'valor_ajuste': valor_ajuste,
            'unidade_padrao': produto['unidade_padrao'],
            'foi_contado': foi_contado
        })
        
        total_produtos += 1
    
    # Estatísticas
    stats = {
        'total_produtos': total_produtos,
        'total_divergencias': total_divergencias,
        'total_entradas': total_entradas,
        'total_saidas': total_saidas,
        'total_ok': total_ok,
        'total_nao_contados': total_nao_contados,
        'valor_total_ajustes': valor_total_ajustes
    }
    
    return render_template(
        'admin/preview_fechamento.html',
        inventario=inv_dict,
        comparacao=comparacao,
        stats=stats,
        nome_categoria=nome_categoria,
        is_gerente=True
    )


@bp.route('/confirmar_fechamento', methods=['POST'])
def confirmar_fechamento():
    """Confirma e executa o fechamento do inventário após revisão."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        flash('Nenhum inventário aberto para fechar.', 'error')
        return redirect(url_for('admin.dashboard'))

    inv_id = inv['id']
    inv_dict = dict(inv)
    
    # Verificar ocorrências pendentes
    ocorrencias_pendentes = db.execute(
        "SELECT COUNT(*) as count FROM ocorrencias WHERE id_inventario = ? AND resolvido = 0",
        (inv_id,)
    ).fetchone()
    if ocorrencias_pendentes['count'] > 0:
        flash(f"❌ Existem {ocorrencias_pendentes['count']} ocorrências pendentes! Resolva todas antes de fechar o inventário.", 'error')
        return redirect(url_for('admin.ocorrencias'))

    # Salvar snapshot do status dos locais
    db.execute("DELETE FROM historico_status_locais WHERE id_inventario = ?", (inv_id,))
    locais = db.execute("SELECT id, status FROM locais").fetchall()
    entries = [(inv_id, l['id'], l['status']) for l in locais]
    if entries:
        db.executemany(
            "INSERT INTO historico_status_locais (id_inventario, id_local, status_registrado) VALUES (?, ?, ?)",
            entries
        )

    # GERAR AJUSTES AUTOMÁTICOS NO KARDEX
    # Buscar usuário Sistema para registrar as movimentações
    usuario_sistema = db.execute("SELECT id FROM usuarios WHERE nome = 'Sistema'").fetchone()
    id_usuario_sistema = usuario_sistema['id'] if usuario_sistema else None
    
    # Determinar escopo dos produtos (COMPLETO ou PARCIAL)
    if inv_dict['tipo_inventario'] == 'PARCIAL' and inv_dict['id_categoria_escopo']:
        # Inventário PARCIAL: apenas produtos da categoria
        sql_produtos_contados = '''
            SELECT 
                p.id as produto_id,
                p.nome as produto_nome,
                p.estoque_atual,
                p.preco_custo,
                COALESCE(SUM(c.quantidade_padrao), 0) as quantidade_contada,
                u.sigla as unidade_padrao
            FROM produtos p
            JOIN produto_categoria_inventario pc ON p.id = pc.id_produto
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.ativo = 1 
            AND p.controla_estoque = 1
            AND pc.id_categoria = ?
            GROUP BY p.id
        '''
        produtos_para_ajustar = db.execute(
            sql_produtos_contados,
            (inv_id, inv_dict['id_categoria_escopo'])
        ).fetchall()
    else:
        # Inventário COMPLETO: todos os produtos ativos
        sql_produtos_contados = '''
            SELECT 
                p.id as produto_id,
                p.nome as produto_nome,
                p.estoque_atual,
                p.preco_custo,
                COALESCE(SUM(c.quantidade_padrao), 0) as quantidade_contada,
                u.sigla as unidade_padrao
            FROM produtos p
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.ativo = 1 AND p.controla_estoque = 1
            GROUP BY p.id
        '''
        produtos_para_ajustar = db.execute(sql_produtos_contados, (inv_id,)).fetchall()
    
    # Processar ajustes
    total_ajustes = 0
    total_entradas = 0
    total_saidas = 0
    
    for produto in produtos_para_ajustar:
        estoque_sistema = float(produto['estoque_atual'] or 0)
        quantidade_contada = float(produto['quantidade_contada'] or 0)
        diferenca = quantidade_contada - estoque_sistema
        
        # Apenas gerar movimentação se houver diferença
        if abs(diferenca) > 0.001:  # Tolerância para erros de arredondamento
            if diferenca > 0:
                # Entrada (contado > sistema)
                registrar_movimento(
                    db=db,
                    produto_id=produto['produto_id'],
                    tipo='ENTRADA',
                    quantidade_original=abs(diferenca),
                    motivo='AJUSTE_INVENTARIO',
                    unidade_movimentacao=produto['unidade_padrao'],
                    fator_conversao=1.0,
                    origem=f'Fechamento Inventário #{inv_id} - Ajuste Automático',
                    usuario_id=id_usuario_sistema,
                    observacao=f'Contado: {quantidade_contada:.2f} | Sistema: {estoque_sistema:.2f} | Diferença: +{diferenca:.2f}'
                )
                total_entradas += 1
            else:
                # Saída (contado < sistema)
                registrar_movimento(
                    db=db,
                    produto_id=produto['produto_id'],
                    tipo='SAIDA',
                    quantidade_original=abs(diferenca),
                    motivo='AJUSTE_INVENTARIO',
                    unidade_movimentacao=produto['unidade_padrao'],
                    fator_conversao=1.0,
                    origem=f'Fechamento Inventário #{inv_id} - Ajuste Automático',
                    usuario_id=id_usuario_sistema,
                    observacao=f'Contado: {quantidade_contada:.2f} | Sistema: {estoque_sistema:.2f} | Diferença: {diferenca:.2f}'
                )
                total_saidas += 1
            
            total_ajustes += 1

    # Resetar status dos locais para próximo inventário
    db.execute("UPDATE locais SET status = 0")

    # Fechar inventário
    db.execute(
        "UPDATE inventarios SET status='Fechado', data_fechamento = CURRENT_TIMESTAMP WHERE id = ? AND status='Aberto'",
        (inv_id,)
    )
    
    db.commit()
    
    # Mensagem de sucesso com detalhes
    if total_ajustes > 0:
        flash(f'✅ Inventário fechado com sucesso! {total_ajustes} ajuste(s) gerado(s): {total_entradas} entrada(s), {total_saidas} saída(s). Locais resetados.', 'success')
    else:
        flash('✅ Inventário fechado com sucesso! Nenhum ajuste necessário (estoque já estava correto). Locais resetados.', 'success')
    
    return redirect(url_for('admin.dashboard'))


@bp.route('/iniciar_novo_inventario', methods=['POST'])
def iniciar_novo_inventario():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    db = get_db()
    db.execute(
        "INSERT INTO inventarios (data_criacao, status, descricao) VALUES (?, ?, ?)",
        (date.today().isoformat(), 'Aberto', 'Iniciado pelo Gerente - Novo Inventário')
    )
    db.execute("UPDATE locais SET status = 0")
    db.commit()
    flash('Novo inventário iniciado. Todos os locais foram resetados.', 'success')
    return redirect(url_for('admin.dashboard'))


@bp.route('/recuperar_ultimo_inventario', methods=['POST'])
def recuperar_ultimo_inventario():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    db = get_db()
    last = db.execute("SELECT id FROM inventarios ORDER BY id DESC LIMIT 1").fetchone()
    if not last:
        flash('Nenhum inventário encontrado para recuperar.', 'error')
        return redirect(url_for('admin.dashboard'))

    inv_id = last['id']
    db.execute("UPDATE inventarios SET status='Aberto' WHERE id = ?", (inv_id,))
    db.execute("UPDATE locais SET status = 0")

    rows = db.execute("SELECT id_local, status_registrado FROM historico_status_locais WHERE id_inventario = ?", (inv_id,)).fetchall()
    for r in rows:
        db.execute("UPDATE locais SET status = ? WHERE id = ?", (r['status_registrado'], r['id_local']))

    db.commit()
    flash('Inventário recuperado e locais restaurados a partir do snapshot.', 'success')
    return redirect(url_for('admin.dashboard'))


@bp.route('/cancelar_inventario', methods=['POST'])
def cancelar_inventario():
    """Cancela o inventário atual SEM alterar o estoque. Usado para cancelar contagens iniciadas por engano."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    # Buscar inventário aberto
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto'").fetchone()
    if not inv:
        flash('❌ Não há inventário aberto para cancelar.', 'error')
        return redirect(url_for('admin.dashboard'))
    
    inv_id = inv['id']
    
    try:
        # Registrar no log ANTES de deletar
        db.execute(
            "INSERT INTO logs_auditoria (acao, descricao, data_hora) VALUES (?, ?, ?)",
            (
                'INVENTARIO_CANCELADO', 
                f'Inventário ID {inv_id} foi CANCELADO e deletado. Nenhuma alteração foi feita no estoque.',
                datetime.now().isoformat()
            )
        )
        
        # Deletar todas as contagens do inventário
        db.execute("DELETE FROM contagens WHERE id_inventario = ?", (inv_id,))
        
        # Deletar histórico de status dos locais
        db.execute("DELETE FROM historico_status_locais WHERE id_inventario = ?", (inv_id,))
        
        # Deletar o inventário
        db.execute("DELETE FROM inventarios WHERE id = ?", (inv_id,))
        
        # Resetar status dos locais para próximo inventário
        db.execute("UPDATE locais SET status = 0")
        
        db.commit()
        
        flash('✅ Inventário cancelado com sucesso. Nenhuma alteração foi feita no estoque.', 'success')
        
    except Exception as e:
        db.rollback()
        flash(f'❌ Erro ao cancelar inventário: {str(e)}', 'error')
    
    return redirect(url_for('admin.dashboard'))


@bp.route('/editar_quantidade', methods=['POST'])
def editar_quantidade():
    if not gerente_required():
        return jsonify({'erro': 'Acesso negado'}), 403
    data = request.get_json()
    db = get_db()
    antiga = db.execute('SELECT * FROM contagens WHERE id=?', (data['contagem_id'],)).fetchone()
    db.execute('UPDATE contagens SET quantidade = ? WHERE id = ?', (data['nova_quantidade'], data['contagem_id']))
    desc = f"Alterou de {antiga['quantidade']} para {data['nova_quantidade']}. Motivo: {data['motivo']}"
    db.execute(
        "INSERT INTO logs_auditoria (acao, descricao, data_hora) VALUES (?, ?, ?)",
        ('CORRECAO_GERENTE', desc, datetime.now().isoformat())
    )
    db.commit()
    return jsonify({'sucesso': True})


@bp.route('/exportar_csv')
def exportar_csv():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        return redirect(url_for('admin.dashboard'))

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
    for r in rows:
        writer.writerow(list(r))

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='inventario.csv'
    )


@bp.route('/exportar_preview_fechamento')
def exportar_preview_fechamento():
    """Exporta a comparação do preview de fechamento para Excel."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        flash('Nenhum inventário aberto.', 'error')
        return redirect(url_for('admin.dashboard'))
    
    inv_id = inv['id']
    inv_dict = dict(inv)
    
    # Determinar escopo dos produtos (mesma lógica do preview)
    if inv_dict['tipo_inventario'] == 'PARCIAL' and inv_dict['id_categoria_escopo']:
        sql_produtos = '''
            SELECT 
                p.id as produto_id,
                p.nome as produto_nome,
                p.id_erp,
                p.gtin,
                p.estoque_atual,
                p.preco_custo,
                COALESCE(SUM(c.quantidade_padrao), 0) as quantidade_contada,
                u.sigla as unidade_padrao,
                COUNT(c.id) as total_contagens
            FROM produtos p
            JOIN produto_categoria_inventario pc ON p.id = pc.id_produto
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.ativo = 1 AND p.controla_estoque = 1 AND pc.id_categoria = ?
            GROUP BY p.id
            ORDER BY p.nome
        '''
        produtos = db.execute(sql_produtos, (inv_id, inv_dict['id_categoria_escopo'])).fetchall()
        categoria = db.execute("SELECT nome FROM categorias_inventario WHERE id = ?", (inv_dict['id_categoria_escopo'],)).fetchone()
        tipo_info = f"PARCIAL - {categoria['nome']}" if categoria else "PARCIAL"
    else:
        sql_produtos = '''
            SELECT 
                p.id as produto_id,
                p.nome as produto_nome,
                p.id_erp,
                p.gtin,
                p.estoque_atual,
                p.preco_custo,
                COALESCE(SUM(c.quantidade_padrao), 0) as quantidade_contada,
                u.sigla as unidade_padrao,
                COUNT(c.id) as total_contagens
            FROM produtos p
            LEFT JOIN contagens c ON p.id = c.id_produto AND c.id_inventario = ?
            LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.ativo = 1 AND p.controla_estoque = 1
            GROUP BY p.id
            ORDER BY p.nome
        '''
        produtos = db.execute(sql_produtos, (inv_id,)).fetchall()
        tipo_info = "COMPLETO"
    
    # Montar dados para Excel
    dados_excel = []
    for produto in produtos:
        estoque_sistema = float(produto['estoque_atual'] or 0)
        quantidade_contada = float(produto['quantidade_contada'] or 0)
        diferenca = quantidade_contada - estoque_sistema
        preco_custo = float(produto['preco_custo'] or 0)
        valor_ajuste = abs(diferenca) * preco_custo
        foi_contado = produto['total_contagens'] > 0
        
        if abs(diferenca) < 0.001:
            tipo_ajuste = 'OK - Sem Ajuste'
        elif diferenca > 0:
            tipo_ajuste = 'ENTRADA'
        else:
            tipo_ajuste = 'SAÍDA'
        
        dados_excel.append({
            'ID ERP': produto['id_erp'] or '-',
            'GTIN': produto['gtin'] or '-',
            'Produto': produto['produto_nome'],
            'Unidade': produto['unidade_padrao'],
            'Estoque Sistema': estoque_sistema,
            'Quantidade Contada': quantidade_contada,
            'Diferença': diferenca,
            'Tipo Ajuste': tipo_ajuste,
            'Preço Custo Unit.': preco_custo,
            'Valor do Ajuste': valor_ajuste,
            'Foi Contado?': 'Sim' if foi_contado else 'Não'
        })
    
    # Criar DataFrame e Excel
    df = pd.DataFrame(dados_excel)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Comparação', index=False)
        
        # Ajustar largura das colunas
        worksheet = writer.sheets['Comparação']
        for idx, col in enumerate(df.columns):
            max_length = max(df[col].astype(str).apply(len).max(), len(col)) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)
    
    output.seek(0)
    
    filename = f'preview_fechamento_inv{inv_id}_{tipo_info}.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# Gestão de produtos


@bp.route('/produtos', methods=['GET', 'POST'])
def admin_produtos():
    is_autorizado = session.get('is_gerente') or session.get('funcao') == 'Estoquista Chefe'
    if not is_autorizado:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'sucesso': False, 'error': 'Permissão negada. Apenas Gerentes ou Chefes.'}), 403
        return redirect(url_for('auth.login_admin'))

    db = get_db()

    if request.method == 'POST':
        produto_id = request.form.get('produto_id')
        nome = request.form.get('nome', '').strip()
        categoria = request.form.get('categoria', '').strip()
        id_unidade_padrao = request.form.get('id_unidade_padrao')
        id_erp = request.form.get('id_erp', '').strip() or None
        gtin = request.form.get('gtin', '').strip() or None
        preco_custo = float(request.form.get('preco_custo', 0) or 0)
        preco_venda = float(request.form.get('preco_venda', 0) or 0)
        ativo = 1 if request.form.get('ativo') else 0
        unidades_permitidas = request.form.getlist('unidades_permitidas')

        if not nome or not id_unidade_padrao:
            error_msg = 'Nome e Unidade Padrão são obrigatórios.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'sucesso': False, 'error': error_msg}), 400
            flash(error_msg, 'error')
        else:
            try:
                if produto_id:
                    db.execute('''
                        UPDATE produtos
                        SET nome = ?, categoria = ?, id_unidade_padrao = ?, id_erp = ?, gtin = ?, preco_custo = ?, preco_venda = ?, ativo = ?
                        WHERE id = ?
                    ''', (nome, categoria or None, int(id_unidade_padrao), id_erp, gtin, preco_custo, preco_venda, ativo, int(produto_id)))
                else:
                    cursor = db.execute('''
                        INSERT INTO produtos (nome, categoria, id_unidade_padrao, id_erp, gtin, preco_custo, preco_venda, ativo)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (nome, categoria or None, int(id_unidade_padrao), id_erp, gtin, preco_custo, preco_venda, ativo))
                    produto_id = cursor.lastrowid

                db.execute('DELETE FROM produtos_unidades WHERE id_produto = ?', (produto_id,))
                db.execute("INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao) VALUES (?, ?, 1.0)", (produto_id, int(id_unidade_padrao)))
                for uid in unidades_permitidas:
                    uid_int = int(uid)
                    if uid_int == int(id_unidade_padrao):
                        continue
                    fator = float(request.form.get(f'fator_{uid_int}', '0').replace(',', '.') or 0)
                    if fator > 0:
                        db.execute(
                            "INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao) VALUES (?, ?, ?)",
                            (produto_id, uid_int, fator)
                        )

                db.commit()
                success_msg = 'Produto salvo com sucesso!'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'sucesso': True, 'produto_id': produto_id, 'message': success_msg}), 200
                flash(success_msg, 'success')
            except Exception as exc:
                db.rollback()
                error_msg = f'Erro: {exc}'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'sucesso': False, 'error': error_msg}), 500
                flash(error_msg, 'error')

        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            return redirect(url_for('admin.admin_produtos'))

    termo = request.args.get('q', '').strip()
    pagina = request.args.get('page', 1, type=int)
    itens_por_pagina = 50

    where_sql = "WHERE (p.ativo=1 or p.ativo=0)"
    params = []
    if termo:
        where_sql += " AND (p.nome LIKE ? OR p.gtin LIKE ? OR p.id_erp LIKE ?)"
        wildcard = f'%{termo}%'
        params = [wildcard, wildcard, wildcard]

    total_itens = db.execute(f"SELECT COUNT(*) as total FROM produtos p {where_sql}", params).fetchone()['total']
    total_paginas = math.ceil(total_itens / itens_por_pagina)
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
    unidades = [dict(r) for r in db.execute("SELECT * FROM unidades_medida ORDER BY sigla").fetchall()]

    return render_template(
        'admin/admin_produtos.html',
        produtos=produtos,
        unidades=unidades,
        busca=termo,
        pagina_atual=pagina,
        total_paginas=total_paginas,
        total_itens=total_itens,
        is_gerente=True
    )


@bp.route('/produto/<int:prod_id>')
def admin_produto_json(prod_id):
    if not session.get('is_gerente') and session.get('funcao') != 'Estoquista Chefe':
        return jsonify({'erro': 'Acesso negado'}), 403

    db = get_db()
    prod = db.execute("SELECT * FROM produtos WHERE id = ?", (prod_id,)).fetchone()
    if not prod:
        return jsonify({'erro': 'Produto não encontrado'}), 404

    units = db.execute("SELECT * FROM produtos_unidades WHERE id_produto = ?", (prod_id,)).fetchall()
    dados = dict(prod)
    dados['unidades_permitidas'] = [dict(u) for u in units]
    return jsonify(dados)


@bp.route('/excluir_item/<int:contagem_id>', methods=['POST'])
def excluir_item(contagem_id):
    if not session.get('user_id'):
        return jsonify({'erro': 'Não autorizado'}), 401

    db = get_db()
    try:
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

        db.execute('DELETE FROM contagens WHERE id = ?', (contagem_id,))
        db.commit()
        return jsonify({'sucesso': True})

    except Exception as exc:
        db.rollback()
        return jsonify({'erro': str(exc)}), 500


# Integração ERP


@bp.route('/upload_erp', methods=['GET', 'POST'])
def upload_erp():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    if request.method == 'GET':
        return render_template('admin/upload_erp.html', is_gerente=True)

    file = request.files.get('arquivo')
    if not file or not file.filename.endswith(('.xlsx', '.xls')):
        flash('Arquivo inválido', 'error')
        return redirect(url_for('admin.upload_erp'))

    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'temp_import.xlsx')
    file.save(filepath)
    return redirect(url_for('admin.analise_importacao'))


@bp.route('/analise_importacao')
def analise_importacao():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'temp_import.xlsx')
    if not os.path.exists(filepath):
        flash('Envie o arquivo primeiro.', 'error')
        return redirect(url_for('admin.upload_erp'))

    try:
        df = pd.read_excel(filepath, dtype={'ID_PRODUTO': str}).fillna('')
    except Exception as exc:
        flash(f'Erro ao ler Excel: {exc}', 'error')
        return redirect(url_for('admin.upload_erp'))

    db = get_db()
    sql_existentes = "SELECT id_erp, nome, preco_venda, preco_custo, gtin, categoria, ativo FROM produtos WHERE id_erp IS NOT NULL"
    raw_db = db.execute(sql_existentes).fetchall()

    existentes_db = {}
    for r in raw_db:
        raw_id = r['id_erp']
        clean_id = str(raw_id).strip().replace('.0', '')
        existentes_db[clean_id] = dict(r)

    print(f"DEBUG DB: Total carregados: {len(existentes_db)}")
    print(f"DEBUG DB: Exemplos de IDs no Banco: {list(existentes_db.keys())[:3]}")

    novos = []
    existentes = []
    print("DEBUG EXCEL: Iniciando loop...")
    contador_debug = 0

    for _, row in df.iterrows():
        raw_id_excel = row.get('ID_PRODUTO', '')
        id_erp = str(raw_id_excel).strip().replace('.0', '')
        if not id_erp or id_erp.lower() == 'nan':
            continue

        if contador_debug < 5:
            match = id_erp in existentes_db
            print(f"CHECK #{contador_debug}: Excel '{id_erp}' (Bruto: {raw_id_excel}) | Existe no Banco? {match}")
            if not match and contador_debug == 0:
                print(f"   -> ATENÇÃO: '{id_erp}' não foi encontrado nas chaves do banco.")
            contador_debug += 1

        nome_xl = str(row.get('PRODUTO', '')).strip()
        cat_xl = str(row.get('Contagem', '')).strip()
        gtin_xl = str(row.get('GTIN', '')).strip()
        if gtin_xl.endswith('.0'):
            gtin_xl = gtin_xl[:-2]

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

            tem_diferenca = False
            if nome_db != nome_xl:
                tem_diferenca = True
            if cat_db != cat_xl:
                tem_diferenca = True
            if gtin_db != gtin_xl:
                tem_diferenca = True
            if abs(custo_db - custo_xl) > 0.001:
                tem_diferenca = True
            if abs(venda_db - venda_xl) > 0.001:
                tem_diferenca = True
            if ativo_db != ativo_xl:
                tem_diferenca = True

            if tem_diferenca:
                existentes.append({
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
                })
        else:
            novos.append({
                'id_erp': id_erp,
                'gtin': gtin_xl,
                'nome': nome_xl,
                'categoria': cat_xl,
                'und_str': str(row.get('UND', '')),
                'preco_custo': custo_xl,
                'preco_venda': venda_xl,
                'ativo': ativo_xl
            })

    print("--- FIM DO DIAGNÓSTICO ---\n")
    return render_template('admin/analise_importacao.html', novos=novos, existentes=existentes, is_gerente=True)


@bp.route('/confirmar_importacao', methods=['POST'])
def confirmar_importacao():
    if not gerente_required():
        return jsonify({'erro': 'Acesso negado'}), 403

    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'temp_import.xlsx')
    if not os.path.exists(filepath):
        return jsonify({'erro': 'Arquivo expirou'}), 400

    ids_selecionados = request.json.get('novos_ids', [])
    df = pd.read_excel(filepath).fillna('')
    db = get_db()
    unidades_map = {r['sigla'].upper(): r['id'] for r in db.execute("SELECT id, sigla FROM unidades_medida").fetchall()}

    count_novos, count_upd = 0, 0

    for _, row in df.iterrows():
        id_erp = str(row.get('ID_PRODUTO', '')).strip()
        if not id_erp:
            continue

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


# CRUD básicos


@bp.route('/categorias', methods=['GET', 'POST'])
def admin_categorias():
    """Gerencia categorias de inventário para contagens parciais."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    if request.method == 'POST':
        action = request.form.get('action')
        categoria_id = request.form.get('categoria_id')
        
        if action == 'delete':
            # Verificar se é a categoria GERAL
            categoria = db.execute(
                'SELECT nome FROM categorias_inventario WHERE id = ?', 
                (categoria_id,)
            ).fetchone()
            
            if categoria and categoria['nome'] == 'GERAL':
                flash('❌ A categoria GERAL não pode ser excluída.', 'error')
            else:
                db.execute(
                    'UPDATE categorias_inventario SET ativo = 0 WHERE id = ?', 
                    (categoria_id,)
                )
                db.commit()
                flash('✅ Categoria desativada com sucesso.', 'success')
        
        elif action == 'save':
            nome = request.form.get('nome', '').strip()
            descricao = request.form.get('descricao', '').strip()
            
            if not nome:
                flash('❌ Nome é obrigatório.', 'error')
            else:
                try:
                    if categoria_id:
                        # Editar categoria existente
                        db.execute('''
                            UPDATE categorias_inventario 
                            SET nome = ?, descricao = ? 
                            WHERE id = ?
                        ''', (nome, descricao, categoria_id))
                        flash('✅ Categoria atualizada com sucesso.', 'success')
                    else:
                        # Criar nova categoria
                        db.execute('''
                            INSERT INTO categorias_inventario (nome, descricao, ativo)
                            VALUES (?, ?, 1)
                        ''', (nome, descricao))
                        flash('✅ Categoria criada com sucesso.', 'success')
                    
                    db.commit()
                except sqlite3.IntegrityError:
                    flash('❌ Já existe uma categoria com esse nome.', 'error')
    
    # Listar categorias ativas com contagem de produtos
    sql_categorias = '''
        SELECT 
            c.id,
            c.nome,
            c.descricao,
            c.data_criacao,
            COUNT(pc.id_produto) as total_produtos
        FROM categorias_inventario c
        LEFT JOIN produto_categoria_inventario pc ON c.id = pc.id_categoria
        WHERE c.ativo = 1
        GROUP BY c.id
        ORDER BY c.nome
    '''
    categorias = [dict(r) for r in db.execute(sql_categorias).fetchall()]
    
    return render_template(
        'admin/admin_categorias.html',
        categorias=categorias,
        is_gerente=True
    )


@bp.route('/categoria/<int:categoria_id>/produtos', methods=['GET', 'POST'])
def categoria_produtos(categoria_id):
    """Gerencia a associação de produtos a uma categoria específica."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    # Buscar dados da categoria
    categoria = db.execute('''
        SELECT * FROM categorias_inventario WHERE id = ? AND ativo = 1
    ''', (categoria_id,)).fetchone()
    
    if not categoria:
        flash('❌ Categoria não encontrada.', 'error')
        return redirect(url_for('admin.admin_categorias'))
    
    categoria = dict(categoria)
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            produto_id = request.form.get('produto_id')
            
            try:
                db.execute('''
                    INSERT INTO produto_categoria_inventario (id_produto, id_categoria)
                    VALUES (?, ?)
                ''', (produto_id, categoria_id))
                db.commit()
                flash('✅ Produto adicionado à categoria.', 'success')
            except sqlite3.IntegrityError:
                flash('⚠️ Produto já está nesta categoria.', 'warning')
        
        elif action == 'remove':
            produto_id = request.form.get('produto_id')
            
            db.execute('''
                DELETE FROM produto_categoria_inventario 
                WHERE id_produto = ? AND id_categoria = ?
            ''', (produto_id, categoria_id))
            db.commit()
            flash('✅ Produto removido da categoria.', 'success')
        
        elif action == 'add_multiple':
            produtos_ids = request.form.getlist('produtos_ids[]')
            
            if produtos_ids:
                adicionados = 0
                for produto_id in produtos_ids:
                    try:
                        db.execute('''
                            INSERT INTO produto_categoria_inventario (id_produto, id_categoria)
                            VALUES (?, ?)
                        ''', (produto_id, categoria_id))
                        adicionados += 1
                    except sqlite3.IntegrityError:
                        continue  # Produto já está na categoria
                
                db.commit()
                flash(f'✅ {adicionados} produto(s) adicionado(s) à categoria.', 'success')
            else:
                flash('⚠️ Nenhum produto selecionado.', 'warning')
    
    # Produtos JÁ associados a esta categoria
    sql_associados = '''
        SELECT 
            p.id,
            p.nome,
            p.categoria as categoria_produto,
            p.id_erp,
            p.gtin,
            u.sigla as unidade_padrao
        FROM produtos p
        JOIN produto_categoria_inventario pc ON p.id = pc.id_produto
        LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
        WHERE pc.id_categoria = ? AND p.ativo = 1
        ORDER BY p.nome
    '''
    produtos_associados = [dict(r) for r in db.execute(sql_associados, (categoria_id,)).fetchall()]
    
    # Produtos DISPONÍVEIS para adicionar (não estão nesta categoria)
    sql_disponiveis = '''
        SELECT 
            p.id,
            p.nome,
            p.categoria as categoria_produto,
            p.id_erp,
            p.gtin,
            u.sigla as unidade_padrao
        FROM produtos p
        LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
        WHERE p.ativo = 1
        AND p.id NOT IN (
            SELECT id_produto 
            FROM produto_categoria_inventario 
            WHERE id_categoria = ?
        )
        ORDER BY p.nome
    '''
    produtos_disponiveis = [dict(r) for r in db.execute(sql_disponiveis, (categoria_id,)).fetchall()]
    
    return render_template(
        'admin/categoria_produtos.html',
        categoria=categoria,
        produtos_associados=produtos_associados,
        produtos_disponiveis=produtos_disponiveis,
        is_gerente=True
    )


@bp.route('/unidades', methods=['GET', 'POST'])
def admin_unidades():
    if not gerente_required():
        flash('Acesso negado.', 'error')
        return redirect(url_for('auth.login_admin'))

    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            unidade_id = request.form.get('unidade_id')
            db.execute('DELETE FROM unidades_medida WHERE id = ?', (unidade_id,))
            db.commit()
            flash('Unidade removida com sucesso!', 'success')
        else:
            sigla = request.form.get('sigla', '').strip().upper()
            nome = request.form.get('nome', '').strip()
            permite_decimal = request.form.get('permite_decimal') == 'on'
            if sigla and nome:
                db.execute(
                    'INSERT INTO unidades_medida (sigla, nome, permite_decimal) VALUES (?, ?, ?)',
                    (sigla, nome, 1 if permite_decimal else 0)
                )
                db.commit()
                flash('Unidade criada com sucesso!', 'success')

    unidades = [dict(r) for r in db.execute("SELECT * FROM unidades_medida ORDER BY sigla").fetchall()]
    return render_template('admin/admin_unidades.html', unidades=unidades, is_gerente=True)


@bp.route('/usuarios', methods=['GET', 'POST'])
def admin_usuarios():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    db = get_db()

    if request.method == 'POST':
        action = request.form.get('action')
        uid = request.form.get('usuario_id')
        if action == 'delete':
            db.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (uid,))
            db.commit()
            flash('Usuário desativado.', 'success')
        elif action == 'save':
            nome = request.form.get('nome')
            funcao = request.form.get('funcao')
            senha = request.form.get('senha')
            ativo = 1 if request.form.get('ativo') == 'on' else 0
            if uid:
                sql = "UPDATE usuarios SET nome=?, funcao=?, ativo=? WHERE id=?"
                params = [nome, funcao, ativo, uid]
                if senha:
                    sql = "UPDATE usuarios SET nome=?, funcao=?, ativo=?, senha=? WHERE id=?"
                    params = [nome, funcao, ativo, senha, uid]
                db.execute(sql, params)
            else:
                db.execute(
                    "INSERT INTO usuarios (nome, funcao, senha, ativo) VALUES (?, ?, ?, ?)",
                    (nome, funcao, senha, ativo)
                )
            db.commit()
            flash('Usuário salvo.', 'success')

    usuarios = [dict(r) for r in db.execute("SELECT * FROM usuarios ORDER BY nome").fetchall()]
    return render_template('admin/admin_usuarios.html', usuarios=usuarios, is_gerente=True)


@bp.route('/setores', methods=['GET', 'POST'])
def admin_setores():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    db = get_db()

    if request.method == 'POST':
        action = request.form.get('action')
        sid = request.form.get('setor_id')

        if action == 'delete':
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

    sql = '''
        SELECT s.*, COUNT(l.id) as total_locais 
        FROM setores s 
        LEFT JOIN locais l ON s.id = l.id_setor AND l.ativo=1
        WHERE s.ativo=1
        GROUP BY s.id 
        ORDER BY s.nome
    '''
    setores = [dict(r) for r in db.execute(sql).fetchall()]
    return render_template('admin/admin_setores.html', setores=setores, is_gerente=True)


@bp.route('/locais', methods=['GET', 'POST'])
def admin_locais():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
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
    return render_template('admin/admin_locais.html', locais=locais, setores=setores, is_gerente=True)


# Ocorrências


@bp.route('/ocorrencias')
def admin_ocorrencias():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    db = get_db()
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
    produtos = [dict(row) for row in db.execute("SELECT id, nome FROM produtos WHERE ativo = 1 ORDER BY nome").fetchall()]
    unidades = [dict(row) for row in db.execute("SELECT * FROM unidades_medida ORDER BY id").fetchall()]

    return render_template(
        'admin/ocorrencias.html',
        ocorrencias=ocorrencias,
        produtos=produtos,
        unidades=unidades,
        is_gerente=True
    )


# Relatórios


@bp.route('/historico')
def historico():
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

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
        ORDER BY i.data_fechamento DESC
    '''
    inventarios = db.execute(sql).fetchall()
    return render_template('admin/historico.html', inventarios=[dict(i) for i in inventarios])


@bp.route('/exportar_excel/<int:inventario_id>')
def exportar_excel(inventario_id):
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))

    import openpyxl
    from openpyxl.styles import Font
    from io import BytesIO

    db = get_db()
    inv = db.execute("SELECT * FROM inventarios WHERE id = ?", (inventario_id,)).fetchone()
    if not inv:
        return "Inventário não encontrado", 404

    sql = '''
        SELECT 
            p.id_erp, 
            p.gtin, 
            p.nome as produto, 
            p.categoria,
            c.quantidade as qtd_informada, 
            u.sigla as unidade_informada,
            c.fator_conversao,
            c.quantidade_padrao,
            c.unidade_padrao_sigla,
            c.preco_custo_snapshot,
            (c.quantidade_padrao * c.preco_custo_snapshot) as valor_total_linha,
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

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Inventario_{inventario_id}"

    headers = [
        "ID ERP", "GTIN", "Produto", "Categoria", 
        "Qtd Informada", "Und Inf.", "Fator Conv.",
        "Qtd Padrão", "Und Padrão",
        "Custo Unit. (Snapshot)", "Valor Total (R$)",
        "Local", "Setor", "Usuário", "Data/Hora"
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for item in itens:
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

    ws.column_dimensions['C'].width = 40
    ws.column_dimensions['H'].width = 15
    ws.column_dimensions['K'].width = 15

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


# Movimentações de Estoque (Kardex)


@bp.route('/lotes/novo')
def lote_novo():
    """Interface para criar novo lote de movimentação."""
    # Não requer verificação gerente_required - qualquer usuário pode criar
    return render_template('admin/lote_novo.html')


@bp.route('/lotes/pendentes')
def lotes_pendentes():
    """Lista lotes aguardando aprovação."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    # Buscar lotes pendentes com informações do usuário criador
    lotes = db.execute('''
        SELECT 
            l.*,
            u.nome as usuario_nome,
            u.funcao as usuario_funcao,
            COUNT(DISTINCT li.id) as total_itens,
            SUM(li.quantidade_original * li.fator_conversao * COALESCE(li.preco_custo_unitario, 0)) as valor_total
        FROM lotes_movimentacao l
        LEFT JOIN usuarios u ON l.id_usuario = u.id
        LEFT JOIN lotes_movimentacao_itens li ON l.id = li.id_lote
        WHERE l.status = 'PENDENTE_APROVACAO'
        GROUP BY l.id
        ORDER BY l.data_criacao ASC
    ''').fetchall()
    
    # Verificar se há lotes anteriores pendentes para cada um (para avisos)
    lotes_com_aviso = []
    for lote in lotes:
        anteriores = db.execute('''
            SELECT COUNT(*) as total
            FROM lotes_movimentacao
            WHERE status = 'PENDENTE_APROVACAO'
              AND data_criacao < ?
              AND id != ?
        ''', (lote['data_criacao'], lote['id'])).fetchone()
        
        lotes_com_aviso.append({
            **dict(lote),
            'lotes_anteriores_pendentes': anteriores['total']
        })
    
    return render_template('admin/lotes_pendentes.html', lotes=lotes_com_aviso)


@bp.route('/lotes/<int:id_lote>')
def lote_detalhe(id_lote):
    """Detalhe de um lote para aprovação/visualização."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    # Buscar lote com dados do criador e aprovador
    lote = db.execute('''
        SELECT 
            l.*,
            u_criador.nome as usuario_criador_nome,
            u_criador.funcao as usuario_criador_funcao,
            u_aprovador.nome as usuario_aprovador_nome,
            so.nome as setor_origem_nome,
            lo.nome as local_origem_nome,
            sd.nome as setor_destino_nome,
            ld.nome as local_destino_nome
        FROM lotes_movimentacao l
        LEFT JOIN usuarios u_criador ON l.id_usuario = u_criador.id
        LEFT JOIN usuarios u_aprovador ON l.id_usuario_aprovador = u_aprovador.id
        LEFT JOIN setores so ON l.setor_origem_id = so.id
        LEFT JOIN locais lo ON l.local_origem_id = lo.id
        LEFT JOIN setores sd ON l.setor_destino_id = sd.id
        LEFT JOIN locais ld ON l.local_destino_id = ld.id
        WHERE l.id = ?
    ''', (id_lote,)).fetchone()
    
    if not lote:
        flash('Lote não encontrado', 'error')
        return redirect(url_for('admin.lotes_pendentes'))
    
    # Buscar itens do lote
    itens = db.execute('''
        SELECT 
            i.*,
            p.nome as produto_nome,
            p.id_erp,
            p.gtin,
            p.estoque_atual,
            um.sigla as unidade_padrao_sigla
        FROM lotes_movimentacao_itens i
        JOIN produtos p ON i.id_produto = p.id
        JOIN unidades_medida um ON p.id_unidade_padrao = um.id
        WHERE i.id_lote = ?
        ORDER BY i.created_at
    ''', (id_lote,)).fetchall()
    
    # Verificar lotes anteriores pendentes
    anteriores = db.execute('''
        SELECT COUNT(*) as total
        FROM lotes_movimentacao
        WHERE status = 'PENDENTE_APROVACAO'
          AND data_criacao < ?
          AND id != ?
    ''', (lote['data_criacao'], id_lote)).fetchone()
    
    return render_template(
        'admin/lote_detalhe.html', 
        lote=dict(lote),
        itens=[dict(i) for i in itens],
        lotes_anteriores_pendentes=anteriores['total']
    )


@bp.route('/movimentacoes')
def movimentacoes():
    """Lista as movimentações de estoque (Kardex)."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    # Filtros opcionais
    produto_id = request.args.get('produto_id', type=int)
    tipo = request.args.get('tipo', '')
    motivo = request.args.get('motivo', '')
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    
    # Paginação
    pagina = request.args.get('page', 1, type=int)
    itens_por_pagina = 50
    offset = (pagina - 1) * itens_por_pagina
    
    # Construir query com filtros
    where_clauses = []
    params = []
    
    if produto_id:
        where_clauses.append('m.id_produto = ?')
        params.append(produto_id)
    
    if tipo:
        where_clauses.append('m.tipo = ?')
        params.append(tipo)
    
    if motivo:
        where_clauses.append('m.motivo = ?')
        params.append(motivo)
    
    if data_inicio:
        where_clauses.append("DATE(m.data_movimento) >= ?")
        params.append(data_inicio)
    
    if data_fim:
        where_clauses.append("DATE(m.data_movimento) <= ?")
        params.append(data_fim)
    
    where_sql = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''
    
    # Query principal
    sql_movimentacoes = f'''
        SELECT 
            m.id,
            m.tipo,
            m.motivo,
            m.quantidade,
            m.unidade_movimentacao,
            m.fator_conversao_usado,
            m.quantidade_original,
            m.preco_custo_unitario,
            m.valor_total,
            m.data_movimento,
            m.origem,
            m.observacao,
            p.id as produto_id,
            p.nome as produto_nome,
            p.id_erp,
            p.estoque_atual,
            u.nome as usuario_nome,
            um.sigla as unidade_padrao
        FROM movimentacoes m
        JOIN produtos p ON m.id_produto = p.id
        LEFT JOIN usuarios u ON m.id_usuario = u.id
        LEFT JOIN unidades_medida um ON p.id_unidade_padrao = um.id
        {where_sql}
        ORDER BY m.data_movimento DESC
        LIMIT ? OFFSET ?
    '''
    
    movimentacoes_lista = [
        dict(r) for r in db.execute(
            sql_movimentacoes, 
            params + [itens_por_pagina, offset]
        ).fetchall()
    ]
    
    # Contar total para paginação
    sql_count = f'''
        SELECT COUNT(*) as total 
        FROM movimentacoes m
        JOIN produtos p ON m.id_produto = p.id
        {where_sql}
    '''
    total = db.execute(sql_count, params).fetchone()['total']
    total_paginas = math.ceil(total / itens_por_pagina)
    
    # Lista de produtos para o filtro
    produtos = [
        dict(r) for r in db.execute(
            'SELECT id, nome, id_erp FROM produtos WHERE ativo = 1 ORDER BY nome'
        ).fetchall()
    ]
    
    # Calcular SALDO INICIAL GLOBAL (soma de todos os produtos antes do período)
    saldo_inicial_global = 0.0
    if data_inicio:
        # Construir WHERE apenas com filtro de produto (se houver)
        where_saldo = []
        params_saldo = []
        
        if produto_id:
            where_saldo.append('id_produto = ?')
            params_saldo.append(produto_id)
        
        where_saldo.append("DATE(data_movimento) < ?")
        params_saldo.append(data_inicio)
        
        where_sql_saldo = 'WHERE ' + ' AND '.join(where_saldo)
        
        sql_saldo_inicial = f'''
            SELECT 
                COALESCE(SUM(CASE WHEN tipo = 'ENTRADA' THEN quantidade ELSE -quantidade END), 0) as saldo
            FROM movimentacoes
            {where_sql_saldo}
        '''
        resultado = db.execute(sql_saldo_inicial, params_saldo).fetchone()
        saldo_inicial_global = float(resultado['saldo'])
    
    # Estatísticas do período
    sql_stats = f'''
        SELECT 
            COALESCE(SUM(CASE WHEN m.tipo = 'ENTRADA' THEN m.quantidade ELSE 0 END), 0) as total_entradas,
            COALESCE(SUM(CASE WHEN m.tipo = 'SAIDA' THEN m.quantidade ELSE 0 END), 0) as total_saidas,
            COUNT(*) as total_movimentacoes,
            COALESCE(SUM(CASE WHEN m.tipo = 'ENTRADA' THEN m.valor_total ELSE 0 END), 0) as valor_entradas,
            COALESCE(SUM(CASE WHEN m.tipo = 'SAIDA' THEN ABS(m.valor_total) ELSE 0 END), 0) as valor_saidas,
            (COALESCE(SUM(CASE WHEN m.tipo = 'ENTRADA' THEN m.valor_total ELSE 0 END), 0) - COALESCE(SUM(CASE WHEN m.tipo = 'SAIDA' THEN ABS(m.valor_total) ELSE 0 END), 0)) as valor_total_movimentacoes
        FROM movimentacoes m
        JOIN produtos p ON m.id_produto = p.id
        {where_sql}
    '''
    stats = dict(db.execute(sql_stats, params).fetchone())
    
    # Adicionar saldo inicial às estatísticas
    stats['saldo_inicial'] = round(saldo_inicial_global, 2)
    
    # Calcular valor em R$ do saldo inicial
    sql_valor_saldo_inicial = f'''
        SELECT 
            COALESCE(SUM(CASE WHEN tipo = 'ENTRADA' THEN valor_total ELSE -valor_total END), 0) as valor
        FROM movimentacoes
        WHERE {"id_produto = ? AND " if produto_id else ""}DATE(data_movimento) < ?
    '''
    params_valor_inicial = [produto_id, data_inicio] if produto_id else [data_inicio]
    
    if data_inicio:
        resultado_valor = db.execute(sql_valor_saldo_inicial, params_valor_inicial).fetchone()
        stats['valor_saldo_inicial'] = round(float(resultado_valor['valor']), 2)
    else:
        stats['valor_saldo_inicial'] = 0.0
    
    # Calcular saldo atual (quantidade): saldo_inicial + entradas - saídas
    stats['saldo_atual'] = round(
        stats['saldo_inicial'] + 
        (stats['total_entradas'] or 0) - 
        (stats['total_saidas'] or 0), 
        2
    )
    
    return render_template(
        'admin/movimentacoes.html',
        movimentacoes=movimentacoes_lista,
        produtos=produtos,
        pagina_atual=pagina,
        total_paginas=total_paginas,
        total_registros=total,
        stats=stats,
        filtros={
            'produto_id': produto_id,
            'tipo': tipo,
            'motivo': motivo,
            'data_inicio': data_inicio,
            'data_fim': data_fim
        },
        is_gerente=True
    )


@bp.route('/estoque_atual')
def estoque_atual():
    """Tela de análise de estoque atual: quantidades, valores e status."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    # Filtros
    busca = request.args.get('busca', '').strip()
    status = request.args.get('status', '').strip()
    categoria_inv = request.args.get('categoria_inv', '').strip()
    curva_abc = request.args.get('curva_abc', '').strip()
    ordenacao = request.args.get('ordenacao', 'nome').strip()
    
    # Paginação
    pagina = request.args.get('page', 1, type=int)
    itens_por_pagina = 50
    
    # Construir WHERE dinâmico
    where_conditions = ["p.ativo = 1"]
    params = []
    
    if busca:
        where_conditions.append("(p.nome LIKE ? OR p.id_erp LIKE ? OR p.gtin LIKE ?)")
        wildcard = f'%{busca}%'
        params.extend([wildcard, wildcard, wildcard])
    
    if curva_abc:
        where_conditions.append("p.curva_abc = ?")
        params.append(curva_abc)
    
    if categoria_inv:
        where_conditions.append('''
            EXISTS (
                SELECT 1 FROM produto_categoria_inventario pc 
                WHERE pc.id_produto = p.id AND pc.id_categoria = ?
            )
        ''')
        params.append(int(categoria_inv))
    
    where_sql = " AND ".join(where_conditions)
    
    # Definir ordenação
    order_map = {
        'nome': 'p.nome ASC',
        'quantidade': 'estoque_atual DESC',
        'valor_total': 'valor_total DESC',
        'ultima_mov': 'ultima_movimentacao DESC'
    }
    order_by = order_map.get(ordenacao, 'p.nome ASC')
    
    # Query principal com estoque e valores
    sql_produtos = f'''
        WITH ultima_mov AS (
            SELECT 
                m1.id_produto,
                m1.data_movimento as ultima_movimentacao,
                m1.tipo as tipo_ultima_mov
            FROM movimentacoes m1
            INNER JOIN (
                SELECT id_produto, MAX(data_movimento) as max_data
                FROM movimentacoes
                GROUP BY id_produto
            ) m2 ON m1.id_produto = m2.id_produto AND m1.data_movimento = m2.max_data
        ),
        saldos_produtos AS (
            SELECT 
                produto_id,
                SUM(saldo) as saldo_total
            FROM estoque_saldos
            GROUP BY produto_id
        )
        SELECT 
            p.id,
            p.nome,
            p.id_erp,
            p.gtin,
            p.categoria,
            p.preco_custo,
            p.curva_abc,
            u.sigla as unidade_padrao,
            COALESCE(sp.saldo_total, 0) as estoque_atual,
            COALESCE(sp.saldo_total, 0) * COALESCE(p.preco_custo, 0) as valor_total,
            um.ultima_movimentacao,
            um.tipo_ultima_mov
        FROM produtos p
        LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
        LEFT JOIN ultima_mov um ON p.id = um.id_produto
        LEFT JOIN saldos_produtos sp ON p.id = sp.produto_id
        WHERE {where_sql}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
    '''
    
    # Contar total para paginação
    sql_count = f'''
        SELECT COUNT(*) as total
        FROM produtos p
        WHERE {where_sql}
    '''
    
    total_itens = db.execute(sql_count, params).fetchone()['total']
    total_paginas = math.ceil(total_itens / itens_por_pagina)
    offset = (pagina - 1) * itens_por_pagina
    
    # Executar query principal
    produtos = [dict(r) for r in db.execute(sql_produtos, params + [itens_por_pagina, offset]).fetchall()]
    
    # Aplicar filtro de status pós-query (mais fácil que fazer no SQL)
    if status:
        if status == 'zerado':
            produtos = [p for p in produtos if p['estoque_atual'] <= 0]
        elif status == 'baixo':
            produtos = [p for p in produtos if 0 < p['estoque_atual'] < 10]
        elif status == 'ok':
            produtos = [p for p in produtos if p['estoque_atual'] >= 10]
        
        # Recalcular paginação após filtro
        total_itens = len(produtos)
        total_paginas = math.ceil(total_itens / itens_por_pagina)
        produtos = produtos[offset:offset + itens_por_pagina]
    
    # Calcular estatísticas globais
    sql_stats = f'''
        WITH saldos AS (
            SELECT produto_id, SUM(saldo) as saldo_total
            FROM estoque_saldos
            GROUP BY produto_id
        )
        SELECT 
            COUNT(DISTINCT p.id) as total_produtos,
            COALESCE(SUM(COALESCE(s.saldo_total, 0) * COALESCE(p.preco_custo, 0)), 0) as valor_total,
            COALESCE(SUM(CASE WHEN COALESCE(s.saldo_total, 0) <= 0 THEN 1 ELSE 0 END), 0) as produtos_zerados,
            COALESCE(SUM(CASE WHEN COALESCE(s.saldo_total, 0) > 0 AND COALESCE(s.saldo_total, 0) < 10 THEN 1 ELSE 0 END), 0) as produtos_baixos,
            COALESCE(SUM(CASE WHEN COALESCE(s.saldo_total, 0) >= 10 THEN 1 ELSE 0 END), 0) as produtos_ok
        FROM produtos p
        LEFT JOIN saldos s ON p.id = s.produto_id
        WHERE p.ativo = 1
    '''
    
    stats = dict(db.execute(sql_stats).fetchone())
    
    # Buscar categorias para o filtro
    categorias = [dict(r) for r in db.execute('''
        SELECT id, nome 
        FROM categorias_inventario 
        WHERE ativo = 1 
        ORDER BY nome
    ''').fetchall()]
    
    return render_template(
        'admin/estoque_atual.html',
        produtos=produtos,
        categorias=categorias,
        stats=stats,
        pagina_atual=pagina,
        total_paginas=total_paginas,
        filtros={
            'busca': busca,
            'status': status,
            'categoria_inv': categoria_inv,
            'curva_abc': curva_abc,
            'ordenacao': ordenacao
        },
        is_gerente=True
    )


@bp.route('/produto_kardex/<int:produto_id>')
def produto_kardex(produto_id):
    """Exibe o extrato completo (Kardex) de um produto específico."""
    if not gerente_required():
        return redirect(url_for('auth.login_admin'))
    
    db = get_db()
    
    # Filtros de data (para uso futuro)
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    
    # Buscar dados do produto
    produto_row = db.execute('''
        SELECT 
            p.id,
            p.nome,
            p.id_erp,
            p.gtin,
            p.categoria,
            p.preco_custo,
            p.controla_estoque,
            p.ativo,
            u.sigla as unidade_sigla,
            u.nome as unidade_nome,
            COALESCE(
                (SELECT SUM(saldo) FROM estoque_saldos WHERE produto_id = p.id),
                0
            ) as estoque_atual
        FROM produtos p
        LEFT JOIN unidades_medida u ON p.id_unidade_padrao = u.id
        WHERE p.id = ?
    ''', (produto_id,)).fetchone()
    
    if not produto_row:
        flash('Produto não encontrado.', 'error')
        return redirect(url_for('admin.movimentacoes'))
    
    produto = dict(produto_row)
    
    # Calcular SALDO INICIAL (antes do período filtrado)
    # Se não houver filtro de data_inicio, saldo inicial = 0 (começou do zero)
    # Se houver filtro, somar todas movimentações ANTES da data_inicio
    saldo_inicial = 0.0
    if data_inicio:
        sql_saldo_inicial = '''
            SELECT 
                COALESCE(SUM(CASE WHEN tipo = 'ENTRADA' THEN quantidade ELSE -quantidade END), 0) as saldo
            FROM movimentacoes
            WHERE id_produto = ? AND DATE(data_movimento) < ?
        '''
        resultado = db.execute(sql_saldo_inicial, (produto_id, data_inicio)).fetchone()
        saldo_inicial = float(resultado['saldo'])
    
    # Construir filtros WHERE para as movimentações
    where_clauses = ['m.id_produto = ?']
    params = [produto_id]
    
    if data_inicio:
        where_clauses.append("DATE(m.data_movimento) >= ?")
        params.append(data_inicio)
    
    if data_fim:
        where_clauses.append("DATE(m.data_movimento) <= ?")
        params.append(data_fim)
    
    where_sql = ' AND '.join(where_clauses)
    
    # Buscar movimentações do período filtrado
    sql_movimentacoes = f'''
        SELECT 
            m.*,
            u.nome as usuario_nome
        FROM movimentacoes m
        LEFT JOIN usuarios u ON m.id_usuario = u.id
        WHERE {where_sql}
        ORDER BY m.data_movimento DESC, m.id DESC
    '''
    
    movimentacoes_raw = db.execute(sql_movimentacoes, params).fetchall()
    
    # Calcular saldo após cada movimentação (do mais antigo para o mais novo)
    movimentacoes_lista = []
    saldo_calculado = saldo_inicial  # Começar do saldo inicial (0 se sem filtro)
    
    # Inverter para calcular do mais antigo para o mais novo
    for mov in reversed(list(movimentacoes_raw)):
        mov_dict = dict(mov)
        
        # A quantidade já está convertida no banco
        if mov_dict['tipo'] == 'ENTRADA':
            saldo_calculado += mov_dict['quantidade']
        else:  # SAIDA
            saldo_calculado -= mov_dict['quantidade']
        
        mov_dict['saldo'] = round(saldo_calculado, 2)
        movimentacoes_lista.insert(0, mov_dict)  # Reinserir na ordem original
    
    # Estatísticas do período filtrado
    sql_stats = f'''
        SELECT 
            SUM(CASE WHEN m.tipo = 'ENTRADA' THEN m.quantidade ELSE 0 END) as total_entradas,
            SUM(CASE WHEN m.tipo = 'SAIDA' THEN m.quantidade ELSE 0 END) as total_saidas,
            COUNT(*) as total_movimentacoes,
            SUM(CASE WHEN m.tipo = 'ENTRADA' THEN m.valor_total ELSE 0 END) as valor_entradas,
            SUM(CASE WHEN m.tipo = 'SAIDA' THEN ABS(m.valor_total) ELSE 0 END) as valor_saidas,
            SUM(m.valor_total) as valor_total_movimentacoes,
            MIN(m.data_movimento) as primeira_data,
            MAX(m.data_movimento) as ultima_data
        FROM movimentacoes m
        WHERE {where_sql}
    '''
    stats = dict(db.execute(sql_stats, params).fetchone())
    
    # Adicionar saldo inicial e final às estatísticas
    stats['saldo_inicial'] = round(saldo_inicial, 2)
    stats['saldo_final'] = round(saldo_calculado, 2)
    
    return render_template(
        'admin/produto_kardex.html',
        produto=produto,
        movimentacoes=movimentacoes_lista,
        stats=stats,
        filtros={
            'data_inicio': data_inicio,
            'data_fim': data_fim
        },
        is_gerente=True
    )

