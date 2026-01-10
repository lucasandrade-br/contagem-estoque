import socket
from datetime import datetime, timedelta


def format_reais(valor):
    """Formata número para padrão brasileiro 1.234,56."""
    if valor is None:
        valor = 0
    try:
        valor_formatado = "{:,.2f}".format(float(valor))
        return valor_formatado.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return valor


def format_datetime_br(valor):
    """Converte datetime UTC para horário de Brasília (UTC-3) e formata."""
    if not valor:
        return '—'
    
    try:
        # Se vier como string, converte para datetime
        if isinstance(valor, str):
            # Tenta vários formatos comuns
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f']:
                try:
                    dt = datetime.strptime(valor, fmt)
                    break
                except ValueError:
                    continue
            else:
                return valor  # Retorna string original se não conseguir parsear
        else:
            dt = valor
        
        # Subtrai 3 horas para converter de UTC para horário de Brasília
        dt_br = dt - timedelta(hours=3)
        
        # Formata no padrão brasileiro
        return dt_br.strftime('%d/%m/%Y %H:%M:%S')
    except Exception:
        return valor


def get_local_ip():
    """Retorna IP local tentando conectar a um host público."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.connect(('8.8.8.8', 80))
        ip = sock.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return ip


def registrar_movimento(db, produto_id, tipo, quantidade_original, motivo, 
                       unidade_movimentacao=None, fator_conversao=1.0, 
                       origem=None, usuario_id=None, observacao=None):
    """
    Registra uma movimentação de estoque (Kardex) e atualiza o saldo do produto.
    
    Args:
        db: Conexão com banco de dados
        produto_id: ID do produto
        tipo: 'ENTRADA' ou 'SAIDA'
        quantidade_original: Quantidade digitada pelo usuário (ex: 13 caixas)
        motivo: 'COMPRA', 'VENDA', 'QUEBRA', 'AJUSTE_INVENTARIO', 'CONSUMO', etc.
        unidade_movimentacao: Sigla da unidade usada (ex: 'CX', 'KG', 'UN')
        fator_conversao: Fator de conversão para unidade padrão (ex: 12.0 para CX->UN)
        origem: Descrição da origem da movimentação (opcional)
        usuario_id: ID do usuário que fez a movimentação (opcional)
        observacao: Observações adicionais (opcional)
    
    Returns:
        int: ID da movimentação criada
        
    Raises:
        ValueError: Se o tipo não for ENTRADA ou SAIDA
        ValueError: Se tentar dar saída maior que estoque disponível
    """
    # Validações
    if tipo not in ['ENTRADA', 'SAIDA']:
        raise ValueError("Tipo deve ser 'ENTRADA' ou 'SAIDA'")
    
    if quantidade_original <= 0:
        raise ValueError("Quantidade deve ser maior que zero")
    
    if fator_conversao <= 0:
        raise ValueError("Fator de conversão deve ser maior que zero")
    
    # Calcular quantidade convertida para unidade padrão
    quantidade_convertida = quantidade_original * fator_conversao
    
    # Buscar dados do produto
    produto = db.execute('''
        SELECT estoque_atual, controla_estoque, nome, id_unidade_padrao, preco_custo
        FROM produtos 
        WHERE id = ?
    ''', (produto_id,)).fetchone()
    
    if not produto:
        raise ValueError(f"Produto ID {produto_id} não encontrado")
    
    estoque_atual = float(produto['estoque_atual'] or 0)
    controla_estoque = int(produto['controla_estoque'])
    preco_custo = float(produto['preco_custo'] or 0.0)
    
    # Se unidade_movimentacao não foi fornecida, usar a unidade padrão
    if not unidade_movimentacao:
        unidade_padrao = db.execute(
            'SELECT sigla FROM unidades_medida WHERE id = ?',
            (produto['id_unidade_padrao'],)
        ).fetchone()
        unidade_movimentacao = unidade_padrao['sigla'] if unidade_padrao else 'UN'
    
    # Verificar se permite estoque negativo (buscar da config)
    config_negativo = db.execute(
        "SELECT valor FROM configs WHERE chave = 'PERMITIR_ESTOQUE_NEGATIVO'"
    ).fetchone()
    permite_negativo = int(config_negativo['valor']) if config_negativo else 0
    
    # Calcular novo saldo (sempre usar quantidade convertida)
    if tipo == 'SAIDA':
        novo_saldo = estoque_atual - quantidade_convertida
        # Verificar se permite estoque negativo
        if not permite_negativo and novo_saldo < 0 and controla_estoque:
            raise ValueError(
                f"Estoque insuficiente! Disponível: {estoque_atual:.2f}, "
                f"Solicitado: {quantidade_convertida:.2f}"
            )
    else:  # ENTRADA
        novo_saldo = estoque_atual + quantidade_convertida
    
    # Calcular valor financeiro da movimentação
    # Usar quantidade ORIGINAL (a que o usuário digitou) para cálculo do valor
    # Exemplo ENTRADA: +10 sacos × R$ 85,00/saco = +R$ 850,00
    # Exemplo SAÍDA: -10 sacos × R$ 85,00/saco = -R$ 850,00
    preco_custo_unitario = preco_custo
    valor_total = quantidade_original * preco_custo_unitario
    
    # Aplicar sinal negativo para SAÍDAs (reduz valor do estoque)
    if tipo == 'SAIDA':
        valor_total = -valor_total
    
    # 1. Inserir movimentação na tabela movimentacoes
    cursor = db.execute('''
        INSERT INTO movimentacoes (
            id_produto, tipo, motivo, quantidade, 
            unidade_movimentacao, fator_conversao_usado, quantidade_original,
            preco_custo_unitario, valor_total,
            data_movimento, origem, id_usuario, observacao
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        produto_id, tipo, motivo, quantidade_convertida,
        unidade_movimentacao, fator_conversao, quantidade_original,
        preco_custo_unitario, valor_total,
        datetime.now().isoformat(), origem, usuario_id, observacao
    ))
    
    movimentacao_id = cursor.lastrowid
    
    # 2. Atualizar saldo na tabela estoque_saldos (apenas se controla_estoque = 1)
    if controla_estoque:
        # Sempre grava em estoque_saldos no modo CENTRAL (setor_id=NULL, local_id=NULL)
        # Calcula a diferença para ajustar o saldo
        diferenca = quantidade_convertida if tipo == 'ENTRADA' else -quantidade_convertida
        
        # UPSERT em estoque_saldos (modo CENTRAL)
        _ajustar_saldo_tabela(db, produto_id, abs(diferenca), 
                             setor_id=None, local_id=None, 
                             incremento=(diferenca > 0))
    
    # 3. Registrar no log de auditoria
    if fator_conversao != 1.0 or unidade_movimentacao:
        acao_desc = f"{tipo} - {motivo}: {quantidade_original:.2f} {unidade_movimentacao} ({quantidade_convertida:.2f} un. padrão) do produto '{produto['nome']}' | Valor: R$ {valor_total:.2f}"
    else:
        acao_desc = f"{tipo} - {motivo}: {quantidade_convertida:.2f} un. do produto '{produto['nome']}' | Valor: R$ {valor_total:.2f}"
    
    if controla_estoque:
        acao_desc += f" | Saldo: {estoque_atual:.2f} → {novo_saldo:.2f}"
    else:
        acao_desc += " | (Produto sem controle de estoque)"
    
    db.execute('''
        INSERT INTO logs_auditoria (acao, descricao, data_hora)
        VALUES (?, ?, ?)
    ''', ('MOVIMENTACAO_ESTOQUE', acao_desc, datetime.now().isoformat()))
    
    return movimentacao_id


def obter_nivel_controle(db):
    """
    Retorna o nível de controle de estoque configurado.
    Prioridade: 1º .env, 2º banco de dados.
    
    Returns:
        str: 'CENTRAL', 'SETOR' ou 'LOCAL'
    """
    from dotenv import load_dotenv
    import os
    
    # 1º: Tentar ler do .env (permite configurar por instalação)
    load_dotenv()
    nivel_env = os.getenv('NIVEL_CONTROLE_ESTOQUE', '').strip().upper()
    
    if nivel_env in ['CENTRAL', 'SETOR', 'LOCAL']:
        return nivel_env
    
    # 2º: Fallback para banco de dados
    config = db.execute(
        "SELECT valor FROM configs WHERE chave = 'NIVEL_CONTROLE_ESTOQUE'"
    ).fetchone()
    
    return config['valor'].upper() if config else 'CENTRAL'


def obter_saldo(db, produto_id, setor_id=None, local_id=None):
    """
    Obtém o saldo de um produto da tabela estoque_saldos.
    
    Args:
        db: Conexão com banco de dados
        produto_id: ID do produto
        setor_id: ID do setor (opcional, None = CENTRAL)
        local_id: ID do local (opcional, None = sem local específico)
    
    Returns:
        float: Saldo disponível
    """
    nivel = obter_nivel_controle(db)
    
    if nivel == 'CENTRAL':
        # Saldo CENTRAL = soma de TODOS os registros do produto em estoque_saldos
        saldo_row = db.execute('''
            SELECT COALESCE(SUM(saldo), 0) as saldo_total
            FROM estoque_saldos 
            WHERE produto_id = ?
        ''', (produto_id,)).fetchone()
        return float(saldo_row['saldo_total']) if saldo_row else 0.0
    
    elif nivel == 'SETOR':
        # Saldo por setor específico
        saldo_row = db.execute('''
            SELECT saldo FROM estoque_saldos 
            WHERE produto_id = ? AND setor_id = ? AND local_id IS NULL
        ''', (produto_id, setor_id)).fetchone()
        return float(saldo_row['saldo']) if saldo_row else 0.0
    
    elif nivel == 'LOCAL':
        # Saldo por local específico
        saldo_row = db.execute('''
            SELECT saldo FROM estoque_saldos 
            WHERE produto_id = ? AND setor_id = ? AND local_id = ?
        ''', (produto_id, setor_id, local_id)).fetchone()
        return float(saldo_row['saldo']) if saldo_row else 0.0
    
    return 0.0


def ajustar_saldo(db, produto_id, quantidade_convertida, tipo, 
                  setor_id=None, local_id=None):
    """
    Ajusta o saldo de um produto na tabela estoque_saldos.
    
    Args:
        db: Conexão com banco de dados
        produto_id: ID do produto
        quantidade_convertida: Quantidade em unidade padrão (positiva)
        tipo: 'ENTRADA', 'SAIDA' ou 'TRANSFERENCIA'
        setor_id: ID do setor (None = CENTRAL)
        local_id: ID do local (None = sem local específico)
    """
    nivel = obter_nivel_controle(db)
    
    # SEMPRE usa estoque_saldos, setor_id/local_id definem o nível
    if nivel == 'CENTRAL':
        # Modo CENTRAL: setor_id e local_id são NULL
        setor_id = None
        local_id = None
    elif nivel == 'SETOR':
        # Modo SETOR: local_id é NULL
        local_id = None
    # elif nivel == 'LOCAL': usa setor_id e local_id fornecidos
    
    # Executar ajuste em estoque_saldos
    if tipo == 'ENTRADA':
        _ajustar_saldo_tabela(db, produto_id, quantidade_convertida, 
                             setor_id, local_id, incremento=True)
    elif tipo == 'SAIDA':
        _ajustar_saldo_tabela(db, produto_id, quantidade_convertida, 
                             setor_id, local_id, incremento=False)
    # TRANSFERENCIA é tratada em lotes.py (SAIDA + ENTRADA)


def _ajustar_saldo_tabela(db, produto_id, quantidade, setor_id, local_id, incremento=True):
    """
    Ajusta saldo na tabela estoque_saldos (UPSERT).
    
    Args:
        incremento: True para adicionar, False para subtrair
    """
    operacao = '+' if incremento else '-'
    
    # Verificar se registro existe
    existe = db.execute('''
        SELECT id FROM estoque_saldos 
        WHERE produto_id = ? AND setor_id = ? AND local_id IS ?
    ''', (produto_id, setor_id, local_id)).fetchone()
    
    if existe:
        # UPDATE
        db.execute(f'''
            UPDATE estoque_saldos 
            SET saldo = saldo {operacao} ? 
            WHERE produto_id = ? AND setor_id = ? AND local_id IS ?
        ''', (quantidade, produto_id, setor_id, local_id))
    else:
        # INSERT
        novo_saldo = quantidade if incremento else -quantidade
        db.execute('''
            INSERT INTO estoque_saldos (produto_id, setor_id, local_id, saldo)
            VALUES (?, ?, ?, ?)
        ''', (produto_id, setor_id, local_id, novo_saldo))


def validar_localizacao(db, tipo, setor_origem_id=None, local_origem_id=None,
                       setor_destino_id=None, local_destino_id=None):
    """
    Valida campos de localização conforme nível de controle e tipo de movimentação.
    
    Returns:
        tuple: (valido: bool, mensagem_erro: str)
    """
    nivel = obter_nivel_controle(db)
    
    if nivel == 'CENTRAL':
        # Não deve ter localização
        if any([setor_origem_id, local_origem_id, setor_destino_id, local_destino_id]):
            return False, "Modo CENTRAL não aceita localização"
        return True, None
    
    elif nivel == 'SETOR':
        if tipo == 'ENTRADA':
            if not setor_destino_id:
                return False, "Modo SETOR: ENTRADA requer setor de destino"
            if local_destino_id:
                return False, "Modo SETOR não aceita locais específicos"
        
        elif tipo == 'SAIDA':
            if not setor_origem_id:
                return False, "Modo SETOR: SAÍDA requer setor de origem"
            if local_origem_id:
                return False, "Modo SETOR não aceita locais específicos"
        
        elif tipo == 'TRANSFERENCIA':
            if not setor_origem_id or not setor_destino_id:
                return False, "Modo SETOR: TRANSFERÊNCIA requer setor de origem e destino"
            if setor_origem_id == setor_destino_id:
                return False, "Origem e destino devem ser diferentes"
            if local_origem_id or local_destino_id:
                return False, "Modo SETOR não aceita locais específicos"
    
    elif nivel == 'LOCAL':
        if tipo == 'ENTRADA':
            if not setor_destino_id or not local_destino_id:
                return False, "Modo LOCAL: ENTRADA requer setor e local de destino"
        
        elif tipo == 'SAIDA':
            if not setor_origem_id or not local_origem_id:
                return False, "Modo LOCAL: SAÍDA requer setor e local de origem"
        
        elif tipo == 'TRANSFERENCIA':
            if not all([setor_origem_id, local_origem_id, setor_destino_id, local_destino_id]):
                return False, "Modo LOCAL: TRANSFERÊNCIA requer setor e local de origem e destino"
            if setor_origem_id == setor_destino_id and local_origem_id == local_destino_id:
                return False, "Origem e destino devem ser diferentes"
    
    return True, None


def obter_requer_aprovacao(db):
    """
    Retorna se movimentações requerem aprovação de gerente.
    Prioridade: 1º .env, 2º banco de dados, 3º default=1 (sim).
    
    Returns:
        int: 0 (não requer/direto) ou 1 (requer aprovação)
    """
    from dotenv import load_dotenv
    import os
    
    # 1º: Tentar ler do .env (permite configurar por instalação)
    load_dotenv()
    requer_env = os.getenv('REQUER_APROVACAO_MOVIMENTACAO', '').strip()
    
    if requer_env in ['0', '1']:
        return int(requer_env)
    
    # 2º: Fallback para banco de dados
    config = db.execute(
        "SELECT valor FROM configs WHERE chave = 'REQUER_APROVACAO_MOVIMENTACAO'"
    ).fetchone()
    
    if config:
        return int(config['valor'])
    
    # 3º: Default = 1 (requer aprovação por segurança)
    return 1
