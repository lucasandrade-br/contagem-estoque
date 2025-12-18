import io
import os
import uuid
from flask import Blueprint, jsonify, request, session, send_file
from ..db import get_db

bp = Blueprint('api', __name__, url_prefix='/api')


@bp.route('/detalhes_local/<int:local_id>')
def api_detalhes_local(local_id):
    if not session.get('is_gerente'):
        return jsonify({'error': 'Acesso negado'}), 403

    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
    if not inv:
        return jsonify([])

    sql = '''
        SELECT p.nome as produto, c.quantidade, um.sigla as unidade, u.nome as usuario, c.data_hora
        FROM contagens c
        JOIN produtos p ON c.id_produto = p.id
        LEFT JOIN unidades_medida um ON c.id_unidade_usada = um.id
        LEFT JOIN usuarios u ON c.id_usuario = u.id
        WHERE c.id_local = ? AND c.id_inventario = ?
        ORDER BY c.data_hora DESC
    '''
    rows = db.execute(sql, (local_id, inv['id'])).fetchall()
    itens = [{'produto': r['produto'], 'quantidade': r['quantidade'], 'unidade': r['unidade'], 'usuario': r['usuario'], 'data_hora': r['data_hora']} for r in rows]
    return jsonify(itens)


@bp.route('/atualizar_produto_rapido', methods=['POST'])
def api_atualizar_produto_rapido():
    if not (session.get('is_gerente') or session.get('funcao') == 'Estoquista Chefe'):
        return jsonify({'error': 'Acesso negado'}), 403

    data = request.get_json() or {}
    produto_id = data.get('produto_id')
    unidades = data.get('unidades', [])

    if not produto_id or not isinstance(unidades, list):
        return jsonify({'error': 'Dados inválidos'}), 400

    db = get_db()
    try:
        for unidade in unidades:
            uid = int(unidade.get('id_unidade'))
            fator = float(unidade.get('fator_conversao'))
            db.execute('''
                INSERT OR REPLACE INTO produtos_unidades (id_produto, id_unidade, fator_conversao)
                VALUES (?, ?, ?)
            ''', (produto_id, uid, fator))
        db.commit()
        return jsonify({'sucesso': True})
    except Exception as exc:
        db.rollback()
        return jsonify({'error': str(exc)}), 500


@bp.route('/registrar_ocorrencia', methods=['POST'])
def api_registrar_ocorrencia():
    if 'user_id' not in session:
        return jsonify({'sucesso': False, 'error': 'Login necessário'}), 401

    db = get_db()
    inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto'").fetchone()
    if not inv:
        return jsonify({'sucesso': False, 'error': 'Nenhum inventário aberto'}), 400

    local_id = request.form.get('local_id', type=int)
    nome = request.form.get('nome', '').strip()
    quantidade = request.form.get('quantidade', type=float)
    unidade_id = request.form.get('unidade_id', type=int)

    if not local_id or not nome or not quantidade or not unidade_id:
        return jsonify({'sucesso': False, 'error': 'Campos obrigatórios: local_id, nome, quantidade, unidade_id'}), 400
    if quantidade <= 0:
        return jsonify({'sucesso': False, 'error': 'Quantidade deve ser maior que zero'}), 400

    foto_path = None
    if 'foto' in request.files:
        foto_file = request.files['foto']
        if foto_file and foto_file.filename:
            try:
                from flask import current_app
                ocorrencias_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'ocorrencias')
                os.makedirs(ocorrencias_dir, exist_ok=True)
                ext = os.path.splitext(foto_file.filename)[1]
                unique_name = f"ocorrencia_{uuid.uuid4().hex}{ext}"
                full_path = os.path.join(ocorrencias_dir, unique_name)
                foto_file.save(full_path)
                foto_path = f'/static/uploads/ocorrencias/{unique_name}'
            except Exception as exc:
                print(f"Erro ao salvar foto: {exc}")
                foto_path = None

    try:
        db.execute('''
            INSERT INTO ocorrencias (id_inventario, id_local, id_usuario, nome_identificado, quantidade, id_unidade, foto_path, resolvido)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        ''', (inv['id'], local_id, session.get('user_id'), nome, quantidade, unidade_id, foto_path))
        db.commit()
        return jsonify({'sucesso': True, 'message': 'Ocorrência registrada com sucesso'}), 200
    except Exception as exc:
        db.rollback()
        return jsonify({'sucesso': False, 'error': str(exc)}), 500


@bp.route('/vincular_ocorrencia', methods=['POST'])
def api_vincular_ocorrencia():
    if not session.get('is_gerente'):
        return jsonify({'erro': 'Acesso negado'}), 403

    data = request.json
    id_ocorrencia = data.get('id_ocorrencia')
    id_produto_destino = data.get('id_produto_destino')
    
    # Novos parâmetros opcionais do modal de validação
    quantidade_editada = data.get('quantidade')  # Pode ser None
    unidade_id_editada = data.get('unidade_id')  # Pode ser None

    db = get_db()
    ocorrencia = db.execute('SELECT * FROM ocorrencias WHERE id = ?', (id_ocorrencia,)).fetchone()
    if not ocorrencia:
        return jsonify({'erro': 'Ocorrência não encontrada'}), 404

    produto = db.execute('''
        SELECT p.preco_custo, p.id_unidade_padrao, u.sigla as sigla_padrao
        FROM produtos p
        JOIN unidades_medida u ON p.id_unidade_padrao = u.id
        WHERE p.id = ?
    ''', (id_produto_destino,)).fetchone()
    if not produto:
        return jsonify({'erro': 'Produto destino não encontrado'}), 404

    # Usa valores editados se fornecidos, senão usa valores originais da ocorrência
    qtd_informada = float(quantidade_editada) if quantidade_editada else float(ocorrencia['quantidade'])
    id_unidade_usada = int(unidade_id_editada) if unidade_id_editada else int(ocorrencia['id_unidade'])
    
    fator_conversao = 1.0
    id_unidade_padrao = int(produto['id_unidade_padrao'])
    if id_unidade_usada != id_unidade_padrao:
        fator_row = db.execute('''
            SELECT fator_conversao FROM produtos_unidades 
            WHERE id_produto = ? AND id_unidade = ?
        ''', (id_produto_destino, id_unidade_usada)).fetchone()
        if fator_row:
            fator_conversao = float(fator_row['fator_conversao'])

    qtd_padrao = qtd_informada * fator_conversao
    preco_snapshot = float(produto['preco_custo'] or 0)
    sigla_snapshot = produto['sigla_padrao']

    try:
        db.execute('''
            INSERT INTO contagens 
            (id_inventario, id_local, id_produto, quantidade, id_unidade_usada, id_usuario, data_hora,
             fator_conversao, quantidade_padrao, preco_custo_snapshot, unidade_padrao_sigla)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
        ''', (
            ocorrencia['id_inventario'],
            ocorrencia['id_local'],
            id_produto_destino,
            qtd_informada,
            id_unidade_usada,
            session.get('user_id'),
            fator_conversao,
            qtd_padrao,
            preco_snapshot,
            sigla_snapshot
        ))

        db.execute('UPDATE ocorrencias SET resolvido = 1, obs = ? WHERE id = ?', (f'Vinculado ao Produto ID {id_produto_destino}', id_ocorrencia))
        db.commit()
        return jsonify({'sucesso': True})
    except Exception as exc:
        db.rollback()
        return jsonify({'erro': str(exc)}), 500


@bp.route('/cadastrar_da_ocorrencia', methods=['POST'])
def cadastrar_da_ocorrencia():
    """
    Cria um novo produto a partir de uma ocorrência.
    Retorna os dados do produto para que o frontend abra o modal de validação.
    A contagem será criada apenas após confirmação no modal de validação.
    """
    if not session.get('is_gerente'):
        return jsonify({'erro': 'Acesso negado'}), 403

    dados = request.form if request.form else request.json
    id_ocorrencia = dados.get('id_ocorrencia')

    db = get_db()
    ocorrencia = db.execute('SELECT * FROM ocorrencias WHERE id = ?', (id_ocorrencia,)).fetchone()
    if not ocorrencia:
        return jsonify({'erro': 'Ocorrência não encontrada'}), 404
    
    try:
        cur = db.cursor()
        
        # Trata campos vazios como NULL para evitar erro de UNIQUE constraint
        id_erp = dados.get('id_erp', '').strip() or None
        gtin = dados.get('gtin', '').strip() or None
        categoria = dados.get('categoria', '').strip() or None
        
        cur.execute('''
            INSERT INTO produtos (nome, id_erp, gtin, categoria, preco_custo, id_unidade_padrao, ativo)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (
            dados.get('nome'),
            id_erp,
            gtin,
            categoria,
            dados.get('preco_custo') or 0,
            dados.get('id_unidade_padrao')
        ))
        novo_prod_id = cur.lastrowid

        # Busca informações completas do novo produto para retornar ao frontend
        novo_produto = db.execute('''
            SELECT 
                p.id, p.nome, p.id_erp, p.gtin, p.categoria, 
                p.preco_custo, p.id_unidade_padrao,
                u.sigla as unidade_padrao_sigla, u.nome as unidade_padrao_nome
            FROM produtos p
            JOIN unidades_medida u ON p.id_unidade_padrao = u.id
            WHERE p.id = ?
        ''', (novo_prod_id,)).fetchone()

        db.commit()
        
        # Retorna os dados do produto criado para o modal de validação
        return jsonify({
            'sucesso': True,
            'produto': {
                'id': novo_produto['id'],
                'nome': novo_produto['nome'],
                'id_erp': novo_produto['id_erp'],
                'gtin': novo_produto['gtin'],
                'categoria': novo_produto['categoria'],
                'preco_custo': novo_produto['preco_custo'],
                'id_unidade_padrao': novo_produto['id_unidade_padrao'],
                'unidade_padrao_sigla': novo_produto['unidade_padrao_sigla'],
                'unidade_padrao_nome': novo_produto['unidade_padrao_nome']
            }
        })
    except Exception as exc:
        db.rollback()
        return jsonify({'erro': str(exc)}), 500


@bp.route('/rejeitar_ocorrencia/<int:id_ocorrencia>', methods=['POST'])
def api_rejeitar_ocorrencia(id_ocorrencia):
    if 'user_id' not in session:
        return jsonify({'sucesso': False, 'error': 'Login necessário'}), 401

    db = get_db()
    try:
        db.execute("UPDATE ocorrencias SET resolvido=1 WHERE id=?", (id_ocorrencia,))
        db.commit()
        return jsonify({'sucesso': True, 'message': 'Ocorrência rejeitada'}), 200
    except Exception as exc:
        db.rollback()
        return jsonify({'sucesso': False, 'error': str(exc)}), 500


@bp.route('/heartbeat')
def heartbeat():
    try:
        db = get_db()
        inv = db.execute("SELECT id FROM inventarios WHERE status='Aberto' LIMIT 1").fetchone()
        if not inv:
            return jsonify({'ativo': False})

        qtd_contagens = db.execute("SELECT COUNT(*) FROM contagens WHERE id_inventario = ?", (inv['id'],)).fetchone()[0]
        qtd_ocorrencias = db.execute("SELECT COUNT(*) FROM ocorrencias WHERE id_inventario = ?", (inv['id'],)).fetchone()[0]
        qtd_locais_finalizados = db.execute("SELECT COUNT(*) FROM locais WHERE status = 2").fetchone()[0]
        versao_dados = qtd_contagens + qtd_ocorrencias + qtd_locais_finalizados
        return jsonify({'ativo': True, 'versao': versao_dados})
    except Exception as exc:
        print(f"Erro no heartbeat: {exc}")
        return jsonify({'ativo': False})


@bp.route('/produto/<int:produto_id>/unidades')
def api_produto_unidades(produto_id):
    """
    Retorna a unidade padrão e unidades alternativas de um produto com seus fatores de conversão.
    Usado no formulário de movimentação de estoque para permitir entrada em diferentes unidades.
    
    Exemplo de retorno:
    {
        "unidade_padrao": {"id": 1, "sigla": "UN", "nome": "Unidade", "fator": 1.0},
        "unidades_alternativas": [
            {"id": 2, "sigla": "CX", "nome": "Caixa", "fator": 12.0},
            {"id": 3, "sigla": "DZ", "nome": "Dúzia", "fator": 12.0}
        ]
    }
    """
    db = get_db()
    
    # Buscar unidade padrão do produto
    produto = db.execute('''
        SELECT p.id_unidade_padrao, um.sigla, um.nome
        FROM produtos p
        JOIN unidades_medida um ON p.id_unidade_padrao = um.id
        WHERE p.id = ?
    ''', (produto_id,)).fetchone()
    
    if not produto:
        return jsonify({'error': 'Produto não encontrado'}), 404
    
    unidade_padrao = {
        'id': produto['id_unidade_padrao'],
        'sigla': produto['sigla'],
        'nome': produto['nome'],
        'fator': 1.0
    }
    
    # Buscar unidades alternativas (relação N:N)
    unidades_alt = db.execute('''
        SELECT um.id, um.sigla, um.nome, pu.fator_conversao
        FROM produtos_unidades pu
        JOIN unidades_medida um ON pu.id_unidade = um.id
        WHERE pu.id_produto = ? AND pu.id_unidade != ?
        ORDER BY um.sigla
    ''', (produto_id, produto['id_unidade_padrao'])).fetchall()
    
    unidades_alternativas = [
        {
            'id': u['id'],
            'sigla': u['sigla'],
            'nome': u['nome'],
            'fator': float(u['fator_conversao'])
        }
        for u in unidades_alt
    ]
    
    return jsonify({
        'unidade_padrao': unidade_padrao,
        'unidades_alternativas': unidades_alternativas
    })

