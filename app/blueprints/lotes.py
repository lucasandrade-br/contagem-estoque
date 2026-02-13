"""
Blueprint para Lotes de Movimentação em massa.
Suporta ENTRADA, SAÍDA e TRANSFERÊNCIA com controle multi-nível (CENTRAL/SETOR/LOCAL).
"""
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from ..db import get_db
from ..utils import (
    obter_nivel_controle, validar_localizacao, obter_saldo, 
    ajustar_saldo, obter_requer_aprovacao, obter_custo_medio
)

bp = Blueprint('lotes', __name__, url_prefix='/lotes')


def ensure_finance_schema(db):
    """Garante tabelas/colunas usadas pelo módulo financeiro."""
    # Coluna de flag de exportação
    cols = [row['name'] for row in db.execute('PRAGMA table_info(lotes_movimentacao)').fetchall()]
    if 'exportado_financeiro' not in cols:
        db.execute("ALTER TABLE lotes_movimentacao ADD COLUMN exportado_financeiro INTEGER NOT NULL DEFAULT 0")

    # Tabelas de referência
    db.execute('''
        CREATE TABLE IF NOT EXISTS fornecedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cnpj TEXT,
            ie TEXT,
            contato TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS planos_contas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT,
            descricao TEXT NOT NULL,
            tipo TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT
        )
    ''')

    # Tabela de dados financeiros do lote
    db.execute('''
        CREATE TABLE IF NOT EXISTS compras_lote (
            id_lote INTEGER PRIMARY KEY,
            id_fornecedor INTEGER NOT NULL,
            id_plano_contas INTEGER NOT NULL,
            num_doc TEXT,
            observacao TEXT,
            valor_total REAL NOT NULL,
            data_emissao TEXT,
            data_vencimento TEXT,
            data_pagamento TEXT,
            valor_pago REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            FOREIGN KEY (id_lote) REFERENCES lotes_movimentacao(id),
            FOREIGN KEY (id_fornecedor) REFERENCES fornecedores(id),
            FOREIGN KEY (id_plano_contas) REFERENCES planos_contas(id)
        )
    ''')

    # Parcelas
    db.execute('''
        CREATE TABLE IF NOT EXISTS compras_parcelas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_lote INTEGER NOT NULL,
            parcela_num INTEGER NOT NULL,
            valor REAL NOT NULL,
            data_vencimento TEXT NOT NULL,
            data_pagamento TEXT,
            valor_pago REAL,
            FOREIGN KEY (id_lote) REFERENCES lotes_movimentacao(id)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_compras_parcelas_lote ON compras_parcelas(id_lote)')


def gerente_required():
    """Verifica se usuário é gerente."""
    return session.get('is_gerente')


def obter_permite_estoque_negativo(db):
    """
    Obtém configuração de estoque negativo.
    Prioridade: .env > banco de dados > padrão (0 = não permite)
    
    Returns:
        bool: True se permite estoque negativo, False caso contrário
    """
    from dotenv import load_dotenv
    import os
    
    load_dotenv()
    permite_env = os.getenv('PERMITIR_ESTOQUE_NEGATIVO', '').strip()
    
    if permite_env in ['0', '1']:
        return bool(int(permite_env))
    
    # Fallback: consultar banco de dados
    config = db.execute(
        "SELECT valor FROM configs WHERE chave = 'PERMITIR_ESTOQUE_NEGATIVO'"
    ).fetchone()
    
    return bool(int(config['valor'])) if config else False


@bp.route('/iniciar', methods=['POST'])
def iniciar_lote():
    """
    Inicia um novo lote de movimentação (rascunho).
    
    Body JSON:
    {
        "tipo": "ENTRADA | SAIDA | TRANSFERENCIA",
        "motivo": "COMPRA | VENDA | ...",
        "setor_origem_id": int (opcional, conforme nível),
        "local_origem_id": int (opcional, conforme nível),
        "setor_destino_id": int (opcional, conforme nível),
        "local_destino_id": int (opcional, conforme nível),
        "origem": "string opcional",
        "observacao": "string opcional"
    }
    
    Returns:
        {"id_lote": int}
    """
    # Temporariamente desabilitado para testes
    # if not gerente_required():
    #     return jsonify({'erro': 'Acesso negado'}), 403
    
    data = request.get_json()
    tipo = data.get('tipo', '').upper()
    motivo = data.get('motivo', '').upper()
    
    if tipo not in ['ENTRADA', 'SAIDA', 'TRANSFERENCIA']:
        return jsonify({'erro': 'Tipo inválido'}), 400
    
    if not motivo:
        return jsonify({'erro': 'Motivo é obrigatório'}), 400
    
    setor_origem_id = data.get('setor_origem_id')
    local_origem_id = data.get('local_origem_id')
    setor_destino_id = data.get('setor_destino_id')
    local_destino_id = data.get('local_destino_id')
    origem = data.get('origem', '').strip()
    observacao = data.get('observacao', '').strip()
    
    db = get_db()
    
    # Validar localização conforme nível configurado
    valido, erro = validar_localizacao(
        db, tipo, setor_origem_id, local_origem_id, 
        setor_destino_id, local_destino_id
    )
    
    if not valido:
        return jsonify({'erro': erro}), 400
    
    try:
        # Usar usuário de movimentação se estiver na sessão, senão usar user_id padrão
        user_id = session.get('user_movimentacao_id') or session.get('user_id')
        
        cursor = db.execute('''
            INSERT INTO lotes_movimentacao (
                tipo, motivo, setor_origem_id, local_origem_id,
                setor_destino_id, local_destino_id, origem, observacao,
                status, id_usuario, data_criacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RASCUNHO', ?, ?)
        ''', (
            tipo, motivo, setor_origem_id, local_origem_id,
            setor_destino_id, local_destino_id, origem, observacao,
            user_id, datetime.now().isoformat()
        ))
        
        id_lote = cursor.lastrowid
        db.commit()
        
        return jsonify({'id_lote': id_lote}), 201
    
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/<int:id_lote>', methods=['GET'])
def obter_lote(id_lote):
    """Retorna detalhes do lote e seus itens."""
    # Temporariamente desabilitado para testes
    # if not gerente_required():
    #     return jsonify({'erro': 'Acesso negado'}), 403
    
    db = get_db()
    
    lote = db.execute('''
        SELECT l.*,
               so.nome as setor_origem_nome,
               lo.nome as local_origem_nome,
               sd.nome as setor_destino_nome,
               ld.nome as local_destino_nome,
               u.nome as usuario_nome
        FROM lotes_movimentacao l
        LEFT JOIN setores so ON l.setor_origem_id = so.id
        LEFT JOIN locais lo ON l.local_origem_id = lo.id
        LEFT JOIN setores sd ON l.setor_destino_id = sd.id
        LEFT JOIN locais ld ON l.local_destino_id = ld.id
        LEFT JOIN usuarios u ON l.id_usuario = u.id
        WHERE l.id = ?
    ''', (id_lote,)).fetchone()
    
    if not lote:
        return jsonify({'erro': 'Lote não encontrado'}), 404
    
    itens = db.execute('''
        SELECT i.*,
               p.nome as produto_nome,
               p.id_erp,
               p.gtin,
               um.sigla as unidade_padrao_sigla
        FROM lotes_movimentacao_itens i
        JOIN produtos p ON i.id_produto = p.id
        JOIN unidades_medida um ON p.id_unidade_padrao = um.id
        WHERE i.id_lote = ?
        ORDER BY i.created_at
    ''', (id_lote,)).fetchall()
    
    return jsonify({
        'lote': dict(lote),
        'itens': [dict(item) for item in itens]
    })


@bp.route('/<int:id_lote>/item', methods=['POST'])
def adicionar_item(id_lote):
    """
    Adiciona um item ao lote.
    
    Body JSON:
    {
        "id_produto": int,
        "quantidade_original": float,
        "unidade_movimentacao": string,
        "fator_conversao": float,
        "preco_custo_unitario": float (opcional, para ENTRADA),
        "observacao": string (opcional)
    }
    """
    # Temporariamente desabilitado para testes
    # if not gerente_required():
    #     return jsonify({'erro': 'Acesso negado'}), 403
    
    db = get_db()
    
    # Verificar se lote existe e está em rascunho
    lote = db.execute(
        'SELECT tipo, status FROM lotes_movimentacao WHERE id = ?',
        (id_lote,)
    ).fetchone()
    
    if not lote:
        return jsonify({'erro': 'Lote não encontrado'}), 404
    
    if lote['status'] not in ('RASCUNHO', 'PENDENTE_APROVACAO'):
        return jsonify({'erro': 'Lote não editável (apenas RASCUNHO ou PENDENTE_APROVACAO)'}), 400
    
    data = request.get_json()
    id_produto = data.get('id_produto')
    quantidade_original = data.get('quantidade_original')
    unidade_movimentacao = data.get('unidade_movimentacao', '').strip()
    fator_conversao = data.get('fator_conversao', 1.0)
    preco_custo_unitario = data.get('preco_custo_unitario')
    observacao = data.get('observacao', '').strip()
    
    if not id_produto or not quantidade_original or quantidade_original <= 0:
        return jsonify({'erro': 'Produto e quantidade são obrigatórios'}), 400
    
    if fator_conversao <= 0:
        return jsonify({'erro': 'Fator de conversão inválido'}), 400
    
    try:
        cursor = db.execute('''
            INSERT INTO lotes_movimentacao_itens (
                id_lote, id_produto, quantidade_original,
                unidade_movimentacao, fator_conversao,
                preco_custo_unitario, observacao, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            id_lote, id_produto, quantidade_original,
            unidade_movimentacao, fator_conversao,
            preco_custo_unitario, observacao,
            datetime.now().isoformat()
        ))
        
        item_id = cursor.lastrowid
        db.commit()
        
        return jsonify({'item_id': item_id}), 201
    
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/<int:id_lote>/item/<int:item_id>', methods=['PUT'])
def editar_item(id_lote, item_id):
    """Edita um item do lote (apenas se status = RASCUNHO)."""
    # Temporariamente desabilitado para testes
    # if not gerente_required():
    #     return jsonify({'erro': 'Acesso negado'}), 403
    
    db = get_db()
    
    # Verificar se lote está em rascunho
    lote = db.execute(
        'SELECT status FROM lotes_movimentacao WHERE id = ?',
        (id_lote,)
    ).fetchone()
    
    if not lote or lote['status'] not in ('RASCUNHO', 'PENDENTE_APROVACAO'):
        return jsonify({'erro': 'Lote não editável'}), 400
    
    data = request.get_json()
    quantidade_original = data.get('quantidade_original')
    fator_conversao = data.get('fator_conversao')
    preco_custo_unitario = data.get('preco_custo_unitario')
    observacao = data.get('observacao')
    
    campos = []
    valores = []
    
    if quantidade_original is not None and quantidade_original > 0:
        campos.append('quantidade_original = ?')
        valores.append(quantidade_original)
    
    if fator_conversao is not None and fator_conversao > 0:
        campos.append('fator_conversao = ?')
        valores.append(fator_conversao)
    
    if preco_custo_unitario is not None:
        campos.append('preco_custo_unitario = ?')
        valores.append(preco_custo_unitario)
    
    if observacao is not None:
        campos.append('observacao = ?')
        valores.append(observacao)
    
    if not campos:
        return jsonify({'erro': 'Nenhum campo para atualizar'}), 400
    
    try:
        valores.extend([item_id, id_lote])
        db.execute(f'''
            UPDATE lotes_movimentacao_itens 
            SET {', '.join(campos)}
            WHERE id = ? AND id_lote = ?
        ''', valores)
        
        db.commit()
        return jsonify({'sucesso': True})
    
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/<int:id_lote>/item/<int:item_id>', methods=['DELETE'])
def remover_item(id_lote, item_id):
    """Remove um item do lote (apenas se status = RASCUNHO)."""
    # Temporariamente desabilitado para testes
    # if not gerente_required():
    #     return jsonify({'erro': 'Acesso negado'}), 403
    
    db = get_db()
    
    # Verificar se lote está editável (RASCUNHO ou PENDENTE_APROVACAO)
    lote = db.execute(
        'SELECT status FROM lotes_movimentacao WHERE id = ?',
        (id_lote,)
    ).fetchone()
    
    if not lote or lote['status'] not in ('RASCUNHO', 'PENDENTE_APROVACAO'):
        return jsonify({'erro': 'Lote não editável (apenas RASCUNHO ou PENDENTE_APROVACAO)'}), 400
    
    try:
        db.execute('''
            DELETE FROM lotes_movimentacao_itens 
            WHERE id = ? AND id_lote = ?
        ''', (item_id, id_lote))
        
        db.commit()
        return jsonify({'sucesso': True})
    
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/<int:id_lote>/finalizar', methods=['POST'])
def finalizar_lote(id_lote):
    """
    Finaliza o lote: valida, gera movimentações e atualiza saldos.
    Esta é a operação crítica que impacta o estoque.
    """
    # Temporariamente desabilitado para testes
    # if not gerente_required():
    #     return jsonify({'erro': 'Acesso negado'}), 403
    
    db = get_db()
    
    # Buscar lote
    lote = db.execute('''
        SELECT * FROM lotes_movimentacao WHERE id = ?
    ''', (id_lote,)).fetchone()
    
    if not lote:
        return jsonify({'erro': 'Lote não encontrado'}), 404
    
    if lote['status'] != 'RASCUNHO':
        return jsonify({'erro': 'Lote já finalizado'}), 400
    
    # Buscar itens
    itens = db.execute('''
        SELECT i.*, p.controla_estoque, p.preco_custo, p.nome as produto_nome
        FROM lotes_movimentacao_itens i
        JOIN produtos p ON i.id_produto = p.id
        WHERE i.id_lote = ?
    ''', (id_lote,)).fetchall()
    
    if not itens:
        return jsonify({'erro': 'Lote sem itens'}), 400
    
    tipo = lote['tipo']
    nivel = obter_nivel_controle(db)
    
    try:
        # Validações por tipo
        if tipo == 'SAIDA':
            # Validar estoque suficiente para cada item
            for item in itens:
                if not item['controla_estoque']:
                    continue
                
                qtd_convertida = item['quantidade_original'] * item['fator_conversao']
                
                if nivel == 'CENTRAL':
                    saldo_atual = obter_saldo(db, item['id_produto'])
                elif nivel == 'SETOR':
                    saldo_atual = obter_saldo(db, item['id_produto'], lote['setor_origem_id'])
                elif nivel == 'LOCAL':
                    saldo_atual = obter_saldo(db, item['id_produto'], 
                                             lote['setor_origem_id'], lote['local_origem_id'])
                
                permite_negativo = obter_permite_estoque_negativo(db)
                
                if not permite_negativo and saldo_atual < qtd_convertida:
                    return jsonify({
                        'erro': f'Estoque insuficiente para {item["produto_nome"]}. '
                               f'Disponível: {saldo_atual:.2f}, Solicitado: {qtd_convertida:.2f}'
                    }), 400
        
        elif tipo == 'TRANSFERENCIA':
            # Validar estoque origem para cada item
            for item in itens:
                if not item['controla_estoque']:
                    continue
                
                qtd_convertida = item['quantidade_original'] * item['fator_conversao']
                
                if nivel == 'SETOR':
                    saldo_origem = obter_saldo(db, item['id_produto'], lote['setor_origem_id'])
                elif nivel == 'LOCAL':
                    saldo_origem = obter_saldo(db, item['id_produto'], 
                                              lote['setor_origem_id'], lote['local_origem_id'])
                else:
                    continue  # TRANSFERENCIA não se aplica a CENTRAL
                
                permite_negativo = obter_permite_estoque_negativo(db)
                
                if not permite_negativo and saldo_origem < qtd_convertida:
                    return jsonify({
                        'erro': f'Estoque insuficiente na origem para {item["produto_nome"]}. '
                               f'Disponível: {saldo_origem:.2f}, Solicitado: {qtd_convertida:.2f}'
                    }), 400
        
        # Verificar se requer aprovação ou vai direto
        requer_aprovacao = obter_requer_aprovacao(db)
        
        if requer_aprovacao == 1:
            # ==================================================
            # MODO COM APROVAÇÃO: PENDENTE_APROVACAO
            # ==================================================
            db.execute('''
                UPDATE lotes_movimentacao 
                SET status = 'PENDENTE_APROVACAO', data_finalizacao = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), id_lote))
            
            total_itens = len(itens)
            db.execute('''
                INSERT INTO logs_auditoria (acao, descricao, data_hora)
                VALUES (?, ?, ?)
            ''', (
                'LOTE_PENDENTE',
                f'Lote #{id_lote} enviado para aprovação: {tipo} com {total_itens} itens',
                datetime.now().isoformat()
            ))
            
            db.commit()
            
            return jsonify({
                'sucesso': True,
                'message': f'Lote #{id_lote} enviado para aprovação do gerente!',
                'total_itens': total_itens,
                'status': 'PENDENTE_APROVACAO'
            })
        
        # ==================================================
        # MODO DIRETO: FINALIZADO (SEM APROVAÇÃO)
        # ==================================================
        # Gerar movimentações e ajustar saldos imediatamente
        for item in itens:
            qtd_convertida = item['quantidade_original'] * item['fator_conversao']

            if tipo == 'TRANSFERENCIA':
                custo_origem = obter_custo_medio(db, item['id_produto'], lote['setor_origem_id'], lote['local_origem_id'])
                custo_unit = custo_origem

                # SAIDA origem
                db.execute('''
                    INSERT INTO movimentacoes (
                        id_produto, tipo, motivo, quantidade,
                        unidade_movimentacao, fator_conversao_usado, quantidade_original,
                        preco_custo_unitario, valor_total,
                        data_movimento, origem, id_usuario, observacao
                    ) VALUES (?, 'SAIDA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id_produto'], lote['motivo'], qtd_convertida,
                    item['unidade_movimentacao'], item['fator_conversao'], item['quantidade_original'],
                    custo_unit, -qtd_convertida * custo_unit,
                    datetime.now().isoformat(), f"Transferência Lote #{id_lote}",
                    session.get('user_id'), f"Lote #{id_lote}"
                ))

                # ENTRADA destino (mantém custo da origem)
                db.execute('''
                    INSERT INTO movimentacoes (
                        id_produto, tipo, motivo, quantidade,
                        unidade_movimentacao, fator_conversao_usado, quantidade_original,
                        preco_custo_unitario, valor_total,
                        data_movimento, origem, id_usuario, observacao
                    ) VALUES (?, 'ENTRADA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id_produto'], lote['motivo'], qtd_convertida,
                    item['unidade_movimentacao'], item['fator_conversao'], item['quantidade_original'],
                    custo_unit, qtd_convertida * custo_unit,
                    datetime.now().isoformat(), f"Transferência Lote #{id_lote}",
                    session.get('user_id'), f"Lote #{id_lote}"
                ))

                if item['controla_estoque']:
                    ajustar_saldo(db, item['id_produto'], qtd_convertida, 'SAIDA',
                                 lote['setor_origem_id'], lote['local_origem_id'])
                    ajustar_saldo(db, item['id_produto'], qtd_convertida, 'ENTRADA',
                                 lote['setor_destino_id'], lote['local_destino_id'], custo_unitario=custo_unit)

            else:
                if tipo == 'SAIDA':
                    preco_custo_unitario = obter_custo_medio(db, item['id_produto'], lote['setor_origem_id'], lote['local_origem_id'])
                    valor_total = -qtd_convertida * preco_custo_unitario
                else:
                    preco_custo_unitario = item['preco_custo_unitario'] or item['preco_custo'] or 0.0
                    valor_total = qtd_convertida * preco_custo_unitario

                db.execute('''
                    INSERT INTO movimentacoes (
                        id_produto, tipo, motivo, quantidade,
                        unidade_movimentacao, fator_conversao_usado, quantidade_original,
                        preco_custo_unitario, valor_total,
                        setor_origem_id, local_origem_id,
                        setor_destino_id, local_destino_id,
                        data_movimento, origem, id_usuario, observacao
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id_produto'], tipo, lote['motivo'], qtd_convertida,
                    item['unidade_movimentacao'], item['fator_conversao'], item['quantidade_original'],
                    preco_custo_unitario, valor_total,
                    lote['setor_origem_id'], lote['local_origem_id'],
                    lote['setor_destino_id'], lote['local_destino_id'],
                    datetime.now().isoformat(), lote['origem'] or f"Lote #{id_lote}",
                    session.get('user_id'), f"Lote #{id_lote}"
                ))

                if item['controla_estoque']:
                    if tipo == 'ENTRADA':
                        ajustar_saldo(db, item['id_produto'], qtd_convertida, tipo,
                                     lote['setor_destino_id'], lote['local_destino_id'], custo_unitario=preco_custo_unitario)
                    else:  # SAIDA
                        ajustar_saldo(db, item['id_produto'], qtd_convertida, tipo,
                                     lote['setor_origem_id'], lote['local_origem_id'])
        
        # Atualizar status do lote para FINALIZADO (modo direto, sem aprovação)
        db.execute('''
            UPDATE lotes_movimentacao 
            SET status = 'FINALIZADO', data_finalizacao = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), id_lote))
        
        # Log de auditoria
        total_itens = len(itens)
        db.execute('''
            INSERT INTO logs_auditoria (acao, descricao, data_hora)
            VALUES (?, ?, ?)
        ''', (
            'LOTE_FINALIZADO_DIRETO',
            f'Lote #{id_lote} finalizado diretamente: {tipo} com {total_itens} itens (sem aprovação)',
            datetime.now().isoformat()
        ))
        
        db.commit()
        
        return jsonify({
            'sucesso': True,
            'message': f'Lote #{id_lote} finalizado com sucesso!',
            'total_itens': total_itens,
            'status': 'FINALIZADO'
        })
    
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'erro': str(e)}), 500


@bp.route('/<int:id_lote>/financeiro', methods=['POST'])
def salvar_financeiro(id_lote):
    """Salva dados financeiros de um lote de ENTRADA (fornecedor, plano, parcelas)."""
    db = get_db()
    ensure_finance_schema(db)

    lote = db.execute('SELECT tipo, status FROM lotes_movimentacao WHERE id = ?', (id_lote,)).fetchone()
    if not lote:
        return jsonify({'erro': 'Lote não encontrado'}), 404
    if lote['tipo'] != 'ENTRADA':
        return jsonify({'erro': 'Dados financeiros só se aplicam a ENTRADA'}), 400

    data = request.get_json() or {}
    id_fornecedor = data.get('id_fornecedor')
    id_plano = data.get('id_plano_contas')
    num_doc = (data.get('num_doc') or '').strip()
    observacao = (data.get('observacao') or '').strip()
    valor_total = float(data.get('valor_total') or 0)
    data_emissao = data.get('data_emissao') or None
    pagamento = data.get('pagamento') or None
    parcelas = data.get('parcelas') or []

    if not id_fornecedor or not id_plano:
        return jsonify({'erro': 'Fornecedor e Plano de Contas são obrigatórios'}), 400
    if valor_total <= 0:
        return jsonify({'erro': 'Valor total inválido'}), 400
    if not parcelas:
        return jsonify({'erro': 'Informe ao menos uma parcela'}), 400

    soma_parcelas = sum(float(p.get('valor') or 0) for p in parcelas)
    if abs(soma_parcelas - valor_total) > 0.05:
        return jsonify({'erro': 'Soma das parcelas não fecha com o valor total'}), 400

    if pagamento:
        if not pagamento.get('data_pagamento') or pagamento.get('valor_pago') is None:
            return jsonify({'erro': 'Informe data e valor do pagamento'}), 400

    # Verifica existência de fornecedor/plano
    for_exists = db.execute('SELECT id FROM fornecedores WHERE id = ? AND ativo = 1', (id_fornecedor,)).fetchone()
    plano_exists = db.execute('SELECT id FROM planos_contas WHERE id = ? AND ativo = 1', (id_plano,)).fetchone()
    if not for_exists or not plano_exists:
        return jsonify({'erro': 'Fornecedor ou Plano de Contas inválido'}), 400

    try:
        # Upsert compras_lote
        db.execute('''
            INSERT INTO compras_lote (id_lote, id_fornecedor, id_plano_contas, num_doc, observacao,
                                      valor_total, data_emissao, data_pagamento, valor_pago, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id_lote) DO UPDATE SET
                id_fornecedor=excluded.id_fornecedor,
                id_plano_contas=excluded.id_plano_contas,
                num_doc=excluded.num_doc,
                observacao=excluded.observacao,
                valor_total=excluded.valor_total,
                data_emissao=excluded.data_emissao,
                data_pagamento=excluded.data_pagamento,
                valor_pago=excluded.valor_pago,
                updated_at=CURRENT_TIMESTAMP
        ''', (
            id_lote, id_fornecedor, id_plano, num_doc, observacao,
            valor_total, data_emissao,
            pagamento.get('data_pagamento') if pagamento else None,
            pagamento.get('valor_pago') if pagamento else None
        ))

        # Substitui parcelas
        db.execute('DELETE FROM compras_parcelas WHERE id_lote = ?', (id_lote,))
        for parc in parcelas:
            db.execute('''
                INSERT INTO compras_parcelas (id_lote, parcela_num, valor, data_vencimento, data_pagamento, valor_pago)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                id_lote,
                int(parc.get('parcela_num') or 0),
                float(parc.get('valor') or 0),
                parc.get('data_vencimento'),
                None,
                None
            ))

        db.commit()
        return jsonify({'sucesso': True})
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500


@bp.route('/<int:id_lote>/aprovar', methods=['POST'])
def aprovar_lote(id_lote):
    """
    Aprova um lote PENDENTE_APROVACAO e aplica as movimentações ao estoque.
    Fluxo eficiente: usa saldo atual + aplica mudanças deste lote (O(1)).
    """
    if not gerente_required():
        return jsonify({'erro': 'Apenas gerentes podem aprovar lotes'}), 403
    
    db = get_db()
    
    # Buscar lote
    lote = db.execute(
        'SELECT * FROM lotes_movimentacao WHERE id = ?',
        (id_lote,)
    ).fetchone()
    
    if not lote:
        return jsonify({'erro': 'Lote não encontrado'}), 404
    
    if lote['status'] != 'PENDENTE_APROVACAO':
        return jsonify({'erro': f'Lote com status {lote["status"]} não pode ser aprovado'}), 400
    
    # Buscar itens
    itens = db.execute('''
        SELECT i.*, p.controla_estoque, p.preco_custo
        FROM lotes_movimentacao_itens i
        JOIN produtos p ON i.id_produto = p.id
        WHERE i.id_lote = ?
    ''', (id_lote,)).fetchall()
    
    if not itens:
        return jsonify({'erro': 'Lote sem itens'}), 400
    
    tipo = lote['tipo']
    nivel = obter_nivel_controle(db)
    
    try:
        # Validar saldo para SAIDA e TRANSFERENCIA (igual ao finalizar)
        if tipo == 'SAIDA':
            for item in itens:
                if not item['controla_estoque']:
                    continue
                
                qtd_convertida = item['quantidade_original'] * item['fator_conversao']
                
                if nivel == 'CENTRAL':
                    saldo_atual = obter_saldo(db, item['id_produto'])
                elif nivel == 'SETOR':
                    saldo_atual = obter_saldo(db, item['id_produto'], lote['setor_origem_id'])
                elif nivel == 'LOCAL':
                    saldo_atual = obter_saldo(db, item['id_produto'], 
                                             lote['setor_origem_id'], lote['local_origem_id'])
                
                permite_negativo = obter_permite_estoque_negativo(db)
                
                if not permite_negativo and saldo_atual < qtd_convertida:
                    return jsonify({
                        'erro': f'Estoque insuficiente para aprovar. '
                               f'Produto: {item["id_produto"]}, '
                               f'Disponível: {saldo_atual:.2f}, Solicitado: {qtd_convertida:.2f}'
                    }), 400
        
        elif tipo == 'TRANSFERENCIA':
            for item in itens:
                if not item['controla_estoque']:
                    continue
                
                qtd_convertida = item['quantidade_original'] * item['fator_conversao']
                
                if nivel == 'SETOR':
                    saldo_origem = obter_saldo(db, item['id_produto'], lote['setor_origem_id'])
                elif nivel == 'LOCAL':
                    saldo_origem = obter_saldo(db, item['id_produto'], 
                                              lote['setor_origem_id'], lote['local_origem_id'])
                else:
                    continue
                
                permite_negativo = obter_permite_estoque_negativo(db)
                
                if not permite_negativo and saldo_origem < qtd_convertida:
                    return jsonify({
                        'erro': f'Estoque insuficiente na origem para aprovar. '
                               f'Produto: {item["id_produto"]}, '
                               f'Disponível: {saldo_origem:.2f}, Solicitado: {qtd_convertida:.2f}'
                    }), 400
        
        # Aplicar movimentações e ajustar saldos (mesmo código do finalizar direto)
        for item in itens:
            qtd_convertida = item['quantidade_original'] * item['fator_conversao']

            if tipo == 'TRANSFERENCIA':
                custo_origem = obter_custo_medio(db, item['id_produto'], lote['setor_origem_id'], lote['local_origem_id'])
                custo_unit = custo_origem

                # SAIDA origem
                db.execute('''
                    INSERT INTO movimentacoes (
                        id_produto, tipo, motivo, quantidade,
                        unidade_movimentacao, fator_conversao_usado, quantidade_original,
                        preco_custo_unitario, valor_total,
                        setor_origem_id, local_origem_id,
                        data_movimento, origem, id_usuario, observacao
                    ) VALUES (?, 'SAIDA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id_produto'], lote['motivo'], qtd_convertida,
                    item['unidade_movimentacao'], item['fator_conversao'], item['quantidade_original'],
                    custo_unit, -qtd_convertida * custo_unit,
                    lote['setor_origem_id'], lote['local_origem_id'],
                    datetime.now().isoformat(), f"Transferência Lote #{id_lote}", 
                    session.get('user_id'), f"Lote #{id_lote}"
                ))
                
                # ENTRADA destino
                db.execute('''
                    INSERT INTO movimentacoes (
                        id_produto, tipo, motivo, quantidade,
                        unidade_movimentacao, fator_conversao_usado, quantidade_original,
                        preco_custo_unitario, valor_total,
                        setor_destino_id, local_destino_id,
                        data_movimento, origem, id_usuario, observacao
                    ) VALUES (?, 'ENTRADA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id_produto'], lote['motivo'], qtd_convertida,
                    item['unidade_movimentacao'], item['fator_conversao'], item['quantidade_original'],
                    custo_unit, qtd_convertida * custo_unit,
                    lote['setor_destino_id'], lote['local_destino_id'],
                    datetime.now().isoformat(), f"Transferência Lote #{id_lote}", 
                    session.get('user_id'), f"Lote #{id_lote}"
                ))
                
                # Ajustar saldos
                if item['controla_estoque']:
                    ajustar_saldo(db, item['id_produto'], qtd_convertida, 'SAIDA',
                                 lote['setor_origem_id'], lote['local_origem_id'])
                    ajustar_saldo(db, item['id_produto'], qtd_convertida, 'ENTRADA',
                                 lote['setor_destino_id'], lote['local_destino_id'], custo_unitario=custo_unit)
            
            else:
                if tipo == 'SAIDA':
                    preco_custo_unitario = obter_custo_medio(db, item['id_produto'], lote['setor_origem_id'], lote['local_origem_id'])
                    valor_total = -qtd_convertida * preco_custo_unitario
                else:
                    preco_custo_unitario = item['preco_custo_unitario'] or item['preco_custo'] or 0.0
                    valor_total = qtd_convertida * preco_custo_unitario
                
                db.execute('''
                    INSERT INTO movimentacoes (
                        id_produto, tipo, motivo, quantidade,
                        unidade_movimentacao, fator_conversao_usado, quantidade_original,
                        preco_custo_unitario, valor_total,
                        setor_origem_id, local_origem_id,
                        setor_destino_id, local_destino_id,
                        data_movimento, origem, id_usuario, observacao
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id_produto'], tipo, lote['motivo'], qtd_convertida,
                    item['unidade_movimentacao'], item['fator_conversao'], item['quantidade_original'],
                    preco_custo_unitario, valor_total,
                    lote['setor_origem_id'], lote['local_origem_id'],
                    lote['setor_destino_id'], lote['local_destino_id'],
                    datetime.now().isoformat(), lote['origem'] or f"Lote #{id_lote}", 
                    session.get('user_id'), f"Lote #{id_lote}"
                ))
                
                # Ajustar saldo
                if item['controla_estoque']:
                    if tipo == 'ENTRADA':
                        ajustar_saldo(db, item['id_produto'], qtd_convertida, tipo,
                                     lote['setor_destino_id'], lote['local_destino_id'], custo_unitario=preco_custo_unitario)
                    else:  # SAIDA
                        ajustar_saldo(db, item['id_produto'], qtd_convertida, tipo,
                                     lote['setor_origem_id'], lote['local_origem_id'])
        
        # Atualizar status do lote para APROVADO
        db.execute('''
            UPDATE lotes_movimentacao 
            SET status = 'APROVADO', 
                data_aprovacao = ?,
                id_usuario_aprovador = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), session.get('user_id'), id_lote))
        
        # Log de auditoria
        total_itens = len(itens)
        db.execute('''
            INSERT INTO logs_auditoria (acao, descricao, data_hora)
            VALUES (?, ?, ?)
        ''', (
            'LOTE_APROVADO',
            f'Lote #{id_lote} aprovado pelo gerente: {tipo} com {total_itens} itens',
            datetime.now().isoformat()
        ))
        
        db.commit()
        
        return jsonify({
            'sucesso': True,
            'message': f'Lote #{id_lote} aprovado com sucesso!',
            'total_itens': total_itens,
            'status': 'APROVADO'
        })
    
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'erro': str(e)}), 500


@bp.route('/<int:id_lote>/rejeitar', methods=['POST'])
def rejeitar_lote(id_lote):
    """
    Rejeita um lote PENDENTE_APROVACAO sem aplicar movimentações.
    """
    if not gerente_required():
        return jsonify({'erro': 'Apenas gerentes podem rejeitar lotes'}), 403
    
    db = get_db()
    data = request.get_json()
    motivo_rejeicao = data.get('motivo', '').strip()
    
    if not motivo_rejeicao:
        return jsonify({'erro': 'Motivo da rejeição é obrigatório'}), 400
    
    # Buscar lote
    lote = db.execute(
        'SELECT * FROM lotes_movimentacao WHERE id = ?',
        (id_lote,)
    ).fetchone()
    
    if not lote:
        return jsonify({'erro': 'Lote não encontrado'}), 404
    
    if lote['status'] != 'PENDENTE_APROVACAO':
        return jsonify({'erro': f'Lote com status {lote["status"]} não pode ser rejeitado'}), 400
    
    try:
        # Atualizar status para REJEITADO
        db.execute('''
            UPDATE lotes_movimentacao 
            SET status = 'REJEITADO', 
                motivo_rejeicao = ?,
                data_aprovacao = ?,
                id_usuario_aprovador = ?
            WHERE id = ?
        ''', (motivo_rejeicao, datetime.now().isoformat(), session.get('user_id'), id_lote))
        
        # Log de auditoria
        db.execute('''
            INSERT INTO logs_auditoria (acao, descricao, data_hora)
            VALUES (?, ?, ?)
        ''', (
            'LOTE_REJEITADO',
            f'Lote #{id_lote} rejeitado pelo gerente. Motivo: {motivo_rejeicao}',
            datetime.now().isoformat()
        ))
        
        db.commit()
        
        return jsonify({
            'sucesso': True,
            'message': f'Lote #{id_lote} rejeitado.',
            'status': 'REJEITADO'
        })
    
    except Exception as e:
        db.rollback()
        return jsonify({'erro': str(e)}), 500
