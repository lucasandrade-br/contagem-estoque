from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, session, jsonify, request
from ..db import get_db

bp = Blueprint('estoque', __name__)


@bp.route('/setores')
def setores():
    db = get_db()
    cursor = db.execute('SELECT * FROM setores WHERE ativo=1 ORDER BY nome')
    return render_template('estoque/setores.html', setores=cursor.fetchall())


@bp.route('/setor/<int:setor_id>')
def setor(setor_id):
    db = get_db()
    setor_row = db.execute('SELECT * FROM setores WHERE id = ? AND ativo=1', (setor_id,)).fetchone()
    if not setor_row:
        return redirect(url_for('estoque.setores'))

    inv = db.execute("SELECT id FROM inventarios WHERE status = 'Aberto' LIMIT 1").fetchone()
    inv_id = inv['id'] if inv else None

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

    return render_template('estoque/locais.html', setor=dict(setor_row), locais=[dict(l) for l in locais])


@bp.route('/contagem/<int:local_id>')
def contagem(local_id):
    db = get_db()
    inv = db.execute("SELECT id, tipo_inventario, id_categoria_escopo FROM inventarios WHERE status='Aberto'").fetchone()
    if not inv:
        return redirect(url_for('estoque.setores'))

    local = db.execute("SELECT * FROM locais WHERE id = ?", (local_id,)).fetchone()

    # Filtra produtos conforme tipo de inventário
    if inv['tipo_inventario'] == 'PARCIAL' and inv['id_categoria_escopo']:
        # Inventário PARCIAL: busca apenas produtos da categoria selecionada
        produtos = [dict(r) for r in db.execute('''
            SELECT DISTINCT p.* 
            FROM produtos p
            INNER JOIN produto_categoria_inventario pci ON p.id = pci.id_produto
            WHERE p.ativo = 1 
              AND pci.id_categoria = ?
              AND (p.categoria IS NULL OR (UPPER(p.categoria) != 'NAO CONTA' AND UPPER(p.categoria) != 'NÃO CONTA'))
            ORDER BY p.nome
        ''', (inv['id_categoria_escopo'],)).fetchall()]
    else:
        # Inventário COMPLETO: busca todos os produtos ativos
        produtos = [dict(r) for r in db.execute(
            "SELECT * FROM produtos WHERE ativo=1 AND (categoria IS NULL OR (UPPER(categoria) != 'NAO CONTA' AND UPPER(categoria) != 'NÃO CONTA')) ORDER BY nome"
        ).fetchall()]

    unidades_rows = db.execute('''
        SELECT pu.*, u.sigla, u.nome, u.permite_decimal 
        FROM produtos_unidades pu JOIN unidades_medida u ON pu.id_unidade = u.id
    ''').fetchall()

    mapa_unidades = {}
    for row in unidades_rows:
        pid = row['id_produto']
        if pid not in mapa_unidades:
            mapa_unidades[pid] = []
        mapa_unidades[pid].append(dict(row))

    for prod in produtos:
        prod['unidades_permitidas'] = mapa_unidades.get(prod['id'], [])

    unidades = [dict(r) for r in db.execute("SELECT * FROM unidades_medida ORDER BY sigla").fetchall()]

    historico = db.execute('''
        SELECT c.*, p.nome as produto_nome, u.sigla as unidade_sigla 
        FROM contagens c 
        JOIN produtos p ON c.id_produto = p.id
        JOIN unidades_medida u ON c.id_unidade_usada = u.id
        WHERE c.id_local = ? AND c.id_inventario = ? ORDER BY c.id DESC
    ''', (local_id, inv['id'])).fetchall()

    return render_template(
        'estoque/contagem.html',
        local=dict(local),
        produtos=produtos,
        unidades=unidades,
        historico=[dict(h) for h in historico],
        inventario_id=inv['id']
    )


@bp.route('/salvar_contagem', methods=['POST'])
def salvar_contagem():
    if 'user_id' not in session:
        return jsonify({'erro': 'Login necessário'}), 401
    data = request.get_json()
    db = get_db()

    try:
        inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
        if not inv:
            return jsonify({'erro': 'Nenhum inventário aberto no momento'}), 400

        produto = db.execute('''
            SELECT p.preco_custo, p.id_unidade_padrao, u.sigla as sigla_padrao
            FROM produtos p
            JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.id = ?
        ''', (data['produto_id'],)).fetchone()

        if not produto:
            return jsonify({'erro': 'Produto não encontrado'}), 404

        fator_conversao = 1.0
        id_unidade_usada = int(data['unidade_id'])
        id_unidade_padrao = int(produto['id_unidade_padrao'])

        if id_unidade_usada != id_unidade_padrao:
            fator_row = db.execute('''
                SELECT fator_conversao FROM produtos_unidades 
                WHERE id_produto = ? AND id_unidade = ?
            ''', (data['produto_id'], id_unidade_usada)).fetchone()
            if fator_row:
                fator_conversao = float(fator_row['fator_conversao'])

        qtd_informada = float(data['quantidade'])
        qtd_padrao_calculada = qtd_informada * fator_conversao
        preco_snapshot = float(produto['preco_custo'] or 0)
        sigla_snapshot = produto['sigla_padrao']

        db.execute('''
            INSERT INTO contagens (
                id_inventario, id_produto, id_local, id_usuario, 
                quantidade, id_unidade_usada, data_hora,
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
            fator_conversao,
            qtd_padrao_calculada,
            preco_snapshot,
            sigla_snapshot
        ))

        db.execute("UPDATE locais SET status = 1 WHERE id = ? AND status = 0", (data['local_id'],))
        db.commit()
        return jsonify({'sucesso': True})

    except Exception as exc:
        db.rollback()
        print(f"Erro ao salvar contagem: {exc}")
        return jsonify({'erro': str(exc)}), 500


@bp.route('/finalizar_local/<int:local_id>', methods=['POST'])
def finalizar_local(local_id):
    db = get_db()
    db.execute("UPDATE locais SET status = 2 WHERE id = ?", (local_id,))
    db.commit()
    return redirect(url_for('estoque.setores'))
