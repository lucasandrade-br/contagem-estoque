"""
Script para popular o banco de dados com dados fictícios de 5 meses
Gera histórico realista de inventários, contagens e movimentações
"""

import sqlite3
import os
import random
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# Caminho do banco de dados
DB_PATH = os.path.join(os.path.dirname(__file__), 'padaria.db')


def criar_dados_basicos(conn):
    """Cria dados básicos caso o banco esteja zerado"""
    cursor = conn.cursor()
    
    print("\n🔧 Verificando e criando dados básicos...")
    
    # 1. Unidades de medida
    cursor.execute("SELECT COUNT(*) FROM unidades_medida")
    if cursor.fetchone()[0] == 0:
        print("  ➕ Criando unidades de medida...")
        unidades = [
            ('KG', 'Quilograma', 1),
            ('LT', 'Litro', 1),
            ('UN', 'Unidade', 0),
            ('CX', 'Caixa', 0),
            ('PC', 'Pacote', 0),
            ('DZ', 'Dúzia', 0)
        ]
        cursor.executemany('''
            INSERT INTO unidades_medida (sigla, nome, permite_decimal)
            VALUES (?, ?, ?)
        ''', unidades)
        print(f"     ✓ {len(unidades)} unidades criadas")
    
    # 2. Setores
    cursor.execute("SELECT COUNT(*) FROM setores")
    if cursor.fetchone()[0] == 0:
        print("  ➕ Criando setores...")
        setores = [('Cozinha',), ('Loja',), ('Almoxarifado',), ('Estoque Seco',)]
        cursor.executemany('INSERT INTO setores (nome) VALUES (?)', setores)
        print(f"     ✓ {len(setores)} setores criados")
    
    # 3. Locais
    cursor.execute("SELECT COUNT(*) FROM locais")
    if cursor.fetchone()[0] == 0:
        print("  ➕ Criando locais...")
        cursor.execute('SELECT id, nome FROM setores')
        setores_data = cursor.fetchall()
        locais = []
        for setor_id, setor_nome in setores_data:
            if setor_nome == 'Cozinha':
                locais.extend([('Bancada 1', setor_id, 0), ('Bancada 2', setor_id, 0)])
            elif setor_nome == 'Loja':
                locais.extend([('Prateleira A', setor_id, 0), ('Prateleira B', setor_id, 0)])
            elif setor_nome == 'Almoxarifado':
                locais.extend([('Estante 1', setor_id, 0), ('Estante 2', setor_id, 0)])
            elif setor_nome == 'Estoque Seco':
                locais.extend([('Zona 1', setor_id, 0), ('Zona 2', setor_id, 0)])
        cursor.executemany('INSERT INTO locais (nome, id_setor, status) VALUES (?, ?, ?)', locais)
        print(f"     ✓ {len(locais)} locais criados")
    
    # 4. Usuários
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        print("  ➕ Criando usuários...")
        usuarios = [
            ('Gerente Fictício', 'Gerente', '1234', 1),
            ('Estoquista 1', 'Estoquista', None, 1),
            ('Estoquista 2', 'Estoquista', None, 1),
            ('Sistema', 'Gerente', None, 1)
        ]
        cursor.executemany('INSERT INTO usuarios (nome, funcao, senha, ativo) VALUES (?, ?, ?, ?)', usuarios)
        print(f"     ✓ {len(usuarios)} usuários criados")
    
    # 5. Produtos fictícios
    cursor.execute("SELECT COUNT(*) FROM produtos WHERE ativo = 1")
    if cursor.fetchone()[0] == 0:
        print("  ➕ Criando produtos fictícios...")
        
        # Buscar IDs das unidades
        cursor.execute('SELECT id, sigla FROM unidades_medida')
        unidades_map = {sigla: id for id, sigla in cursor.fetchall()}
        
        produtos_ficticios = [
            ('Farinha de Trigo Tipo 1', 'Ingredientes', unidades_map['KG'], 4.50, 8.00, 0, 'A', 0, 1),
            ('Açúcar Refinado', 'Ingredientes', unidades_map['KG'], 3.20, 6.00, 0, 'A', 0, 1),
            ('Fermento Biológico Seco', 'Ingredientes', unidades_map['PC'], 8.90, 15.00, 0, 'B', 0, 1),
            ('Sal Refinado', 'Ingredientes', unidades_map['KG'], 1.50, 3.00, 0, 'C', 0, 1),
            ('Manteiga sem Sal', 'Ingredientes', unidades_map['KG'], 18.00, 32.00, 0, 'A', 0, 1),
            ('Ovos Grandes', 'Ingredientes', unidades_map['DZ'], 12.00, 20.00, 0, 'A', 0, 1),
            ('Leite Integral', 'Ingredientes', unidades_map['LT'], 4.50, 8.00, 0, 'B', 0, 1),
            ('Chocolate em Pó', 'Ingredientes', unidades_map['KG'], 22.00, 38.00, 0, 'B', 0, 1),
            ('Fermento Químico', 'Ingredientes', unidades_map['PC'], 5.50, 10.00, 0, 'C', 0, 1),
            ('Essência de Baunilha', 'Ingredientes', unidades_map['UN'], 8.00, 15.00, 0, 'C', 0, 1),
            ('Coco Ralado', 'Ingredientes', unidades_map['KG'], 15.00, 28.00, 0, 'B', 0, 1),
            ('Amido de Milho', 'Ingredientes', unidades_map['KG'], 6.50, 12.00, 0, 'C', 0, 1),
            ('Creme de Leite', 'Ingredientes', unidades_map['UN'], 4.00, 7.50, 0, 'B', 0, 1),
            ('Gelatina sem Sabor', 'Ingredientes', unidades_map['PC'], 3.50, 6.50, 0, 'C', 0, 1),
            ('Glacê Pronto', 'Ingredientes', unidades_map['KG'], 12.00, 22.00, 0, 'B', 0, 1),
        ]
        
        cursor.executemany('''
            INSERT INTO produtos (
                nome, categoria, id_unidade_padrao, preco_custo, preco_venda,
                estoque_atual, curva_abc, abc_fixo, controla_estoque
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', produtos_ficticios)
        
        # Criar relações produtos_unidades
        cursor.execute('SELECT id, id_unidade_padrao FROM produtos')
        relacoes = [(prod_id, id_unidade, 1.0) for prod_id, id_unidade in cursor.fetchall()]
        cursor.executemany('''
            INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao)
            VALUES (?, ?, ?)
        ''', relacoes)
        
        print(f"     ✓ {len(produtos_ficticios)} produtos criados")
    
    # 6. Categoria de inventário GERAL
    cursor.execute("SELECT COUNT(*) FROM categorias_inventario")
    if cursor.fetchone()[0] == 0:
        print("  ➕ Criando categoria GERAL...")
        cursor.execute('''
            INSERT INTO categorias_inventario (nome, descricao, ativo)
            VALUES ('GERAL', 'Todos os produtos ativos', 1)
        ''')
        id_categoria = cursor.lastrowid
        
        # Associar todos os produtos à categoria GERAL
        cursor.execute('''
            INSERT INTO produto_categoria_inventario (id_produto, id_categoria)
            SELECT id, ? FROM produtos WHERE ativo = 1
        ''', (id_categoria,))
        print("     ✓ Categoria GERAL criada e produtos associados")
    
    conn.commit()
    print("  ✅ Dados básicos verificados/criados")


def popular_dados_ficticios():
    """Popula o banco com dados fictícios de 5 meses"""
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("="*60)
    print("📊 POPULANDO BANCO COM DADOS FICTÍCIOS DE 5 MESES")
    print("="*60)
    
    # ============================================
    # 0. CRIAR DADOS BÁSICOS SE NECESSÁRIO
    # ============================================
    
    criar_dados_basicos(conn)
    
    # ============================================
    # 1. BUSCAR DADOS EXISTENTES
    # ============================================
    
    print("\n📋 Buscando dados existentes...")
    
    # Produtos ativos
    cursor.execute("SELECT id, nome, preco_custo, id_unidade_padrao FROM produtos WHERE ativo = 1")
    produtos = cursor.fetchall()
    if not produtos:
        print("❌ Erro: Nenhum produto encontrado mesmo após criação!")
        conn.close()
        return
    
    # Locais ativos
    cursor.execute("SELECT id FROM locais WHERE ativo = 1")
    locais = [row[0] for row in cursor.fetchall()]
    if not locais:
        print("❌ Nenhum local encontrado!")
        conn.close()
        return
    
    # Usuários
    cursor.execute("SELECT id FROM usuarios WHERE ativo = 1")
    usuarios = [row[0] for row in cursor.fetchall()]
    if not usuarios:
        usuarios = [1]  # Fallback para admin
    
    # Unidades
    cursor.execute("SELECT id, sigla FROM unidades_medida")
    unidades = {row[0]: row[1] for row in cursor.fetchall()}
    
    print(f"✓ {len(produtos)} produtos encontrados")
    print(f"✓ {len(locais)} locais encontrados")
    print(f"✓ {len(usuarios)} usuários encontrados")
    
    # ============================================
    # 2. GERAR INVENTÁRIOS DOS ÚLTIMOS 5 MESES
    # ============================================
    
    print("\n📅 Gerando inventários dos últimos 5 meses...")
    
    hoje = datetime.now()
    data_inicio = hoje - relativedelta(months=5)
    
    inventarios_criados = []
    
    # Gera inventários mensais (1 por mês)
    for mes in range(5):
        data_inventario = data_inicio + relativedelta(months=mes)
        data_criacao = data_inventario.replace(day=1)
        data_fechamento = data_criacao + timedelta(days=random.randint(2, 5))
        
        cursor.execute('''
            INSERT INTO inventarios (data_criacao, data_fechamento, status, descricao, tipo_inventario)
            VALUES (?, ?, 'Fechado', ?, 'COMPLETO')
        ''', (
            data_criacao.strftime('%Y-%m-%d'),
            data_fechamento.strftime('%Y-%m-%d'),
            f"Inventário Mensal - {data_criacao.strftime('%B/%Y')}"
        ))
        
        id_inventario = cursor.lastrowid
        inventarios_criados.append({
            'id': id_inventario,
            'data': data_criacao,
            'fechamento': data_fechamento
        })
        
        print(f"  ✓ Inventário #{id_inventario}: {data_criacao.strftime('%d/%m/%Y')}")
    
    # ============================================
    # 3. GERAR CONTAGENS PARA CADA INVENTÁRIO
    # ============================================
    
    print("\n📦 Gerando contagens para cada inventário...")
    
    total_contagens = 0
    
    for inv in inventarios_criados:
        id_inventario = inv['id']
        data_base = inv['data']
        
        # Para cada produto, gera contagens em 60-80% dos locais (simula contagem real)
        locais_a_contar = random.sample(locais, k=int(len(locais) * random.uniform(0.6, 0.8)))
        
        for produto_id, produto_nome, preco_custo, id_unidade_padrao in produtos:
            
            # Variação realista de estoque (entre 5 e 200 unidades)
            estoque_base = random.uniform(5, 200)
            
            for local_id in locais_a_contar:
                # Quantidade variada por local
                quantidade = round(estoque_base * random.uniform(0.1, 1.5), 2)
                
                # Data/hora aleatória dentro do período do inventário
                horas_offset = random.randint(0, (inv['fechamento'] - data_base).days * 24)
                data_hora = data_base + timedelta(hours=horas_offset)
                
                # Usuario aleatório
                id_usuario = random.choice(usuarios)
                
                # Unidade usada (normalmente a padrão, às vezes outra)
                id_unidade_usada = id_unidade_padrao
                fator_conversao = 1.0
                unidade_sigla = unidades.get(id_unidade_padrao, 'UN')
                
                # Insere contagem
                cursor.execute('''
                    INSERT INTO contagens (
                        id_inventario, id_produto, id_local, id_usuario,
                        quantidade, id_unidade_usada, fator_conversao, quantidade_padrao,
                        preco_custo_snapshot, unidade_padrao_sigla, data_hora
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    id_inventario, produto_id, local_id, id_usuario,
                    quantidade, id_unidade_usada, fator_conversao, quantidade,
                    preco_custo or 0.0, unidade_sigla, data_hora.strftime('%Y-%m-%d %H:%M:%S')
                ))
                
                total_contagens += 1
        
        print(f"  ✓ Inventário #{id_inventario}: {total_contagens} contagens acumuladas")
    
    # ============================================
    # 4. GERAR MOVIMENTAÇÕES (KARDEX)
    # ============================================
    
    print("\n💸 Gerando movimentações (entradas/saídas)...")
    
    motivos_entrada = ['COMPRA', 'DEVOLUÇÃO', 'AJUSTE_INVENTARIO', 'TRANSFERÊNCIA']
    motivos_saida = ['VENDA', 'QUEBRA', 'CONSUMO', 'AJUSTE_INVENTARIO', 'TRANSFERÊNCIA']
    
    total_movimentacoes = 0
    
    # Para cada mês, gera movimentações diárias
    for mes in range(5):
        data_mes = data_inicio + relativedelta(months=mes)
        dias_no_mes = 30
        
        for dia in range(dias_no_mes):
            data_movimento = data_mes + timedelta(days=dia)
            
            # Gera 5-15 movimentações por dia
            num_movimentacoes = random.randint(5, 15)
            
            for _ in range(num_movimentacoes):
                produto_id, produto_nome, preco_custo, id_unidade_padrao = random.choice(produtos)
                tipo = random.choice(['ENTRADA', 'SAIDA'])
                motivo = random.choice(motivos_entrada if tipo == 'ENTRADA' else motivos_saida)
                quantidade = round(random.uniform(1, 50), 2)
                unidade_sigla = unidades.get(id_unidade_padrao, 'UN')
                valor_total = round(quantidade * (preco_custo or 0.0), 2)
                id_usuario = random.choice(usuarios)
                
                # Hora aleatória do dia
                hora = random.randint(6, 22)
                minuto = random.randint(0, 59)
                data_hora = data_movimento.replace(hour=hora, minute=minuto)
                
                cursor.execute('''
                    INSERT INTO movimentacoes (
                        id_produto, tipo, motivo, quantidade, unidade_movimentacao,
                        fator_conversao_usado, quantidade_original, preco_custo_unitario,
                        valor_total, data_movimento, origem, id_usuario, observacao
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    produto_id, tipo, motivo, quantidade, unidade_sigla,
                    1.0, quantidade, preco_custo or 0.0, valor_total,
                    data_hora.strftime('%Y-%m-%d %H:%M:%S'),
                    'Sistema Fictício', id_usuario, f'Movimentação fictícia - {motivo}'
                ))
                
                total_movimentacoes += 1
        
        print(f"  ✓ Mês {mes+1}/5: {total_movimentacoes} movimentações acumuladas")
    
    # ============================================
    # 5. ATUALIZAR ESTOQUE_ATUAL DOS PRODUTOS
    # ============================================
    
    print("\n📊 Atualizando estoque atual dos produtos...")
    
    for produto_id, _, _, _ in produtos:
        # Calcula estoque baseado nas movimentações
        cursor.execute('''
            SELECT 
                SUM(CASE WHEN tipo = 'ENTRADA' THEN quantidade ELSE -quantidade END)
            FROM movimentacoes
            WHERE id_produto = ?
        ''', (produto_id,))
        
        resultado = cursor.fetchone()
        estoque_atual = resultado[0] if resultado[0] else 0
        
        # Garante estoque positivo (adiciona entrada de ajuste se necessário)
        if estoque_atual < 0:
            estoque_atual = random.uniform(10, 100)
            
            cursor.execute('''
                INSERT INTO movimentacoes (
                    id_produto, tipo, motivo, quantidade, unidade_movimentacao,
                    fator_conversao_usado, quantidade_original, preco_custo_unitario,
                    valor_total, data_movimento, origem, id_usuario, observacao
                ) VALUES (?, 'ENTRADA', 'AJUSTE_INVENTARIO', ?, 'UN', 1.0, ?, 0, 0, ?, 'Sistema', 1, 'Ajuste automático')
            ''', (produto_id, estoque_atual, estoque_atual, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        # Atualiza estoque_atual na tabela produtos
        cursor.execute('UPDATE produtos SET estoque_atual = ? WHERE id = ?', (round(estoque_atual, 2), produto_id))
    
    print("  ✓ Estoque atual atualizado para todos os produtos")
    
    # ============================================
    # 6. COMMIT E ESTATÍSTICAS FINAIS
    # ============================================
    
    conn.commit()
    conn.close()
    
    print("\n" + "="*60)
    print("✅ DADOS FICTÍCIOS INSERIDOS COM SUCESSO!")
    print("="*60)
    print(f"📅 Inventários criados: {len(inventarios_criados)}")
    print(f"📦 Contagens registradas: {total_contagens}")
    print(f"💸 Movimentações geradas: {total_movimentacoes}")
    print(f"📊 Produtos atualizados: {len(produtos)}")
    print("="*60)
    print("\n💡 Dica: Use os relatórios e gráficos para visualizar esses dados!")
    print()


if __name__ == "__main__":
    try:
        popular_dados_ficticios()
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
