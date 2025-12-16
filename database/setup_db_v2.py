"""
Script de setup do banco de dados SQLite - VERSÃO 2.0
Sistema de Contagem de Estoque Padaria - Agora com Controle de Kardex/Extrato
Cria todas as tabelas e insere dados iniciais (seed data).

PRINCIPAIS NOVIDADES V2:
- Tabela movimentacoes: Extrato completo de entradas/saídas (Kardex)
- Tabela configs: Parametrizações globais do sistema
- Produtos com estoque_atual, curva_abc, abc_fixo, controla_estoque
- Snapshots mantidos na tabela contagens (compatibilidade com V1)
"""

import sqlite3
import os
from datetime import datetime, date

# Caminho do banco de dados
DB_PATH = os.path.join(os.path.dirname(__file__), 'padaria.db')


def criar_tabelas(conn):
    cursor = conn.cursor()
    
    print("\n📋 Criando tabelas básicas ...")
    
    # 1. Tabela unidades_medida
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unidades_medida (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sigla TEXT NOT NULL UNIQUE,
            nome TEXT NOT NULL,
            permite_decimal INTEGER NOT NULL DEFAULT 0
        )
    ''')
    
    # 2. Tabela usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            funcao TEXT NOT NULL CHECK(funcao IN ('Gerente', 'Estoquista', 'Estoquista Chefe')),
            senha TEXT,
            ativo INTEGER NOT NULL DEFAULT 1
        )
    ''')
    
    # 3. Tabela setores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS setores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            ativo INTEGER NOT NULL DEFAULT 1
        )
    ''')
    
    # 4. Tabela locais
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS locais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            id_setor INTEGER NOT NULL,
            status INTEGER NOT NULL DEFAULT 0 CHECK(status IN (0, 1, 2)),
            ativo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (id_setor) REFERENCES setores(id) ON DELETE CASCADE
        )
    ''')

    # 4b. Tabela de histórico de status dos locais (snapshot)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historico_status_locais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_inventario INTEGER NOT NULL,
            id_local INTEGER NOT NULL,
            status_registrado INTEGER NOT NULL CHECK(status_registrado IN (0,1,2)),
            FOREIGN KEY (id_inventario) REFERENCES inventarios(id) ON DELETE CASCADE,
            FOREIGN KEY (id_local) REFERENCES locais(id) ON DELETE CASCADE
        )
    ''')
    
    print("✓ Tabelas básicas criadas: unidades_medida, usuarios, setores, locais")
    
    # 5. Tabela inventarios (V2.1 - Com tipo e categoria de escopo)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_criacao DATE NOT NULL,
            data_fechamento DATE,
            status TEXT NOT NULL CHECK(status IN ('Aberto', 'Fechado')),
            descricao TEXT,
            tipo_inventario TEXT DEFAULT 'COMPLETO' CHECK(tipo_inventario IN ('COMPLETO', 'PARCIAL')),
            id_categoria_escopo INTEGER,
            FOREIGN KEY (id_categoria_escopo) REFERENCES categorias_inventario(id) ON DELETE SET NULL
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_inventarios_tipo 
        ON inventarios(tipo_inventario)
    ''')
    
    
    # 5a. Tabela categorias_inventario
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categorias_inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            descricao TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 5b. Tabela de relacionamento N:N entre produtos e categorias de inventário
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produto_categoria_inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_produto INTEGER NOT NULL,
            id_categoria INTEGER NOT NULL,
            data_vinculo DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(id_produto, id_categoria),
            FOREIGN KEY (id_produto) REFERENCES produtos(id) ON DELETE CASCADE,
            FOREIGN KEY (id_categoria) REFERENCES categorias_inventario(id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_produto_categoria_produto 
        ON produto_categoria_inventario(id_produto)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_produto_categoria_categoria 
        ON produto_categoria_inventario(id_categoria)
    ''')
    
    # 5. Tabela produtos - VERSÃO 2.0 com novas colunas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_erp TEXT,
            gtin TEXT,
            nome TEXT NOT NULL,
            categoria TEXT,
            id_unidade_padrao INTEGER NOT NULL,
            preco_custo REAL DEFAULT 0.0,
            preco_venda REAL DEFAULT 0.0,
            ativo INTEGER DEFAULT 1,
            
            -- NOVAS COLUNAS V2
            estoque_atual REAL DEFAULT 0,
            curva_abc TEXT DEFAULT 'C' CHECK(curva_abc IN ('A', 'B', 'C')),
            abc_fixo INTEGER DEFAULT 0 CHECK(abc_fixo IN (0, 1)),
            controla_estoque INTEGER DEFAULT 1 CHECK(controla_estoque IN (0, 1)),
            
            FOREIGN KEY (id_unidade_padrao) REFERENCES unidades_medida(id)
        )
    ''')
    
    # Criar índice UNIQUE para id_erp
    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_produtos_id_erp 
        ON produtos(id_erp) WHERE id_erp IS NOT NULL
    ''')
    
    # Criar índices para performance em consultas por Curva ABC
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_produtos_curva_abc 
        ON produtos(curva_abc) WHERE ativo = 1
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_produtos_controla_estoque 
        ON produtos(controla_estoque) WHERE ativo = 1
    ''')
    
    # 5b. Tabela de relacionamento produtos_unidades (N:N) com fator de conversão
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos_unidades (
            id_produto INTEGER NOT NULL,
            id_unidade INTEGER NOT NULL,
            fator_conversao REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (id_produto, id_unidade),
            FOREIGN KEY (id_produto) REFERENCES produtos(id) ON DELETE CASCADE,
            FOREIGN KEY (id_unidade) REFERENCES unidades_medida(id)
        )
    ''')
      
    # 7. Tabela contagens - Mantém snapshots da V1
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_inventario INTEGER NOT NULL,
            id_produto INTEGER NOT NULL,
            id_local INTEGER NOT NULL,
            id_usuario INTEGER NOT NULL,
            quantidade REAL NOT NULL,
            id_unidade_usada INTEGER NOT NULL,
                   
            -- Snapshots (mantidos da V1 para histórico)
            fator_conversao REAL NOT NULL,
            quantidade_padrao REAL NOT NULL,    
            preco_custo_snapshot REAL NOT NULL, 
            unidade_padrao_sigla TEXT NOT NULL,     

            data_hora DATETIME NOT NULL,
            FOREIGN KEY (id_inventario) REFERENCES inventarios(id) ON DELETE CASCADE,
            FOREIGN KEY (id_produto) REFERENCES produtos(id) ON DELETE CASCADE,
            FOREIGN KEY (id_local) REFERENCES locais(id) ON DELETE CASCADE,
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY (id_unidade_usada) REFERENCES unidades_medida(id)
        )
    ''')
    
    # Índices para performance em contagens
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_contagens_inventario 
        ON contagens(id_inventario)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_contagens_produto 
        ON contagens(id_produto, id_inventario)
    ''')
     
    # NOVA TABELA V2: movimentacoes (O Extrato/Kardex)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_produto INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('ENTRADA', 'SAIDA')),
            motivo TEXT NOT NULL,
            quantidade REAL NOT NULL,
            unidade_movimentacao TEXT,
            fator_conversao_usado REAL DEFAULT 1.0,
            quantidade_original REAL,
            preco_custo_unitario REAL DEFAULT 0.0,
            valor_total REAL DEFAULT 0.0,
            data_movimento DATETIME DEFAULT CURRENT_TIMESTAMP,
            origem TEXT,
            id_usuario INTEGER,
            observacao TEXT,
            FOREIGN KEY (id_produto) REFERENCES produtos(id) ON DELETE CASCADE,
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id) ON DELETE SET NULL
        )
    ''')
    
    # Índices para performance em consultas de movimentações
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_movimentacoes_produto 
        ON movimentacoes(id_produto, data_movimento DESC)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_movimentacoes_tipo 
        ON movimentacoes(tipo, motivo)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_movimentacoes_data 
        ON movimentacoes(data_movimento DESC)
    ''')
    
    print("\n🆕 Criando tabela CONFIGS (Parametrização Global)...")
    
    # NOVA TABELA V2: configs (Parametrização)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configs (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            descricao TEXT,
            data_atualizacao DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
       
    # 8. Tabela logs_auditoria
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs_auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acao TEXT NOT NULL,
            descricao TEXT,
            data_hora DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Índice para performance em logs
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_logs_data 
        ON logs_auditoria(data_hora DESC)
    ''')
    
    # 9. Tabela ocorrencias (Itens não cadastrados ou avulsos)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ocorrencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_inventario INTEGER NOT NULL,
            id_local INTEGER NOT NULL,
            id_usuario INTEGER,
            nome_identificado TEXT NOT NULL,
            quantidade REAL NOT NULL,
            id_unidade INTEGER NOT NULL,
            foto_path TEXT,
            resolvido INTEGER NOT NULL DEFAULT 0,
            obs TEXT,
            data_hora DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (id_inventario) REFERENCES inventarios(id) ON DELETE CASCADE,
            FOREIGN KEY (id_local) REFERENCES locais(id) ON DELETE CASCADE,
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id) ON DELETE SET NULL,
            FOREIGN KEY (id_unidade) REFERENCES unidades_medida(id)
        )
    ''')
    
    # Índice para ocorrências pendentes
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_ocorrencias_resolvido 
        ON ocorrencias(resolvido, id_inventario)
    ''')
    
    conn.commit()
    print("\n✅ Todas as tabelas foram criadas com sucesso!")


def inserir_dados_iniciais(conn):
    """Insere dados de teste (seed data) no banco."""
    cursor = conn.cursor()
    
    print("\n📦 Inserindo dados iniciais...")
    
    # Unidades de medida
    unidades = [
        ('KG', 'Quilograma', 1),
        ('LT', 'Litro', 1),
        ('UN', 'Unidade', 0),
        ('CX', 'Caixa', 0),
        ('FD', 'Fardo', 0),
        ('SC', 'Saco', 0),
        ('PC', 'Pacote', 0),
        ('DZ', 'Dúzia', 0)
    ]
    cursor.executemany('''
        INSERT INTO unidades_medida (sigla, nome, permite_decimal)
        VALUES (?, ?, ?)
    ''', unidades)
    print("✓ Unidades de medida inseridas (8 unidades)")
    
    # Setores
    setores = [
        ('Cozinha',),
        ('Loja',),
        ('Almoxarifado',)
    ]
    cursor.executemany('''
        INSERT INTO setores (nome)
        VALUES (?)
    ''', setores)
    print("✓ Setores inseridos (4 setores)")
    
    # Buscar IDs dos setores para criar locais
    cursor.execute('SELECT id, nome FROM setores')
    setores_data = cursor.fetchall()
    
    # Locais (2-3 para cada setor)
    locais = []
    for setor_id, setor_nome in setores_data:
        if setor_nome == 'Cozinha':
            locais.extend([
                ('Local 1', setor_id, 0),
                ('Local 2', setor_id, 0)
            ])
        elif setor_nome == 'Loja':
            locais.extend([
                ('Prateleira A', setor_id, 0),
                ('Prateleira B', setor_id, 0)
            ])
        elif setor_nome == 'Almoxarifado':
            locais.extend([
                ('Estante 1', setor_id, 0),
                ('Estante 2', setor_id, 0)
            ])
        elif setor_nome == 'Estoque Seco':
            locais.extend([
                ('Prateleira 1', setor_id, 0),
                ('Prateleira 2', setor_id, 0)
            ])
    
    cursor.executemany('''
        INSERT INTO locais (nome, id_setor, status)
        VALUES (?, ?, ?)
    ''', locais)
    print(f"✓ Locais inseridos ({len(locais)} locais)")
    
    # Usuários
    usuarios = [
        ('Lucas', 'Gerente', '2706', 1),
        ('Funcionario 1', 'Estoquista', None, 1),
        ('Funcionario 2', 'Estoquista', None, 1),
        ('Funcionario Chefe', 'Estoquista Chefe', None, 1),
        ('Sistema', 'Gerente', None, 1)  # Usuário para operações automáticas
    ]
    cursor.executemany('''
        INSERT INTO usuarios (nome, funcao, senha, ativo)
        VALUES (?, ?, ?, ?)
    ''', usuarios)
    print("✓ Usuários inseridos (5 usuários)")
    
    # Buscar IDs das unidades para criar produtos
    cursor.execute('SELECT id, sigla FROM unidades_medida')
    unidades_data = {sigla: id for id, sigla in cursor.fetchall()}
    
    
    
    # Produtos_unidades: cada produto aceita sua unidade padrão (fator 1.0)
    cursor.execute('SELECT id, id_unidade_padrao FROM produtos')
    relacoes = [(prod_id, id_unidade, 1.0) for prod_id, id_unidade in cursor.fetchall()]
    cursor.executemany('''
        INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao)
        VALUES (?, ?, ?)
    ''', relacoes)
    print("✓ Relações produtos_unidades inseridas (fator 1.0)")
    
    print("\n⚙️ Inserindo configurações iniciais do sistema...")
    
    # Configs iniciais OBRIGATÓRIAS V2
    configs = [
        ('MODO_ABC', 'MANUAL', 'Define se a Curva ABC é calculada automaticamente (AUTOMATICO) ou gerenciada manualmente (MANUAL)'),
        ('ATUALIZAR_ESTOQUE_COM_VENDA', '0', 'Se 1, cada venda baixa o estoque_atual automaticamente. Se 0, apenas movimentações manuais afetam.'),
        ('DIAS_PERIODO_ABC', '90', 'Número de dias usados para calcular volume de vendas na Curva ABC automática'),
        ('PERCENTUAL_CURVA_A', '80', 'Percentual de faturamento que define produtos Curva A'),
        ('PERCENTUAL_CURVA_B', '95', 'Percentual acumulado que define produtos Curva B (restante vai para C)'),
        ('PERMITIR_ESTOQUE_NEGATIVO', '1', 'Se 1, permite saldo negativo. Se 0, bloqueia saídas que zerariam o estoque'),
        ('VERSAO_BANCO', '2.0', 'Versão do schema do banco de dados')
    ]
    
    cursor.executemany('''
        INSERT INTO configs (chave, valor, descricao)
        VALUES (?, ?, ?)
    ''', configs)
    print(f"✓ Configurações inseridas ({len(configs)} configs)")

    # Categoria GERAL (todos os produtos ativos)
    cursor.execute('''
        INSERT INTO categorias_inventario (nome, descricao, ativo)
        VALUES (?, ?, ?)
    ''', ('GERAL', 'Categoria padrão contendo todos os produtos ativos para inventários completos', 1))
    
    id_categoria_geral = cursor.lastrowid
    print("✓ Categoria GERAL criada")
    
    # Associar todos os produtos ativos à categoria GERAL
    cursor.execute('''
        INSERT INTO produto_categoria_inventario (id_produto, id_categoria)
        SELECT id, ? FROM produtos WHERE ativo = 1
    ''', (id_categoria_geral,))
    
    total_associados = cursor.rowcount
    print(f"✓ {total_associados} produtos ativos associados à categoria GERAL")
    
    # Inventário inicial (Fechado)
    cursor.execute('''
        INSERT INTO inventarios (data_criacao, status, descricao, tipo_inventario, id_categoria_escopo)
        VALUES (?, ?, ?, ?, ?)
    ''', (date.today().isoformat(), 'Fechado', 'Inventário inicial V2 - Sistema migrado', 'COMPLETO', id_categoria_geral))
    print("\n✓ Inventário inicial inserido (status: Fechado, tipo: COMPLETO)")
    
    # Obter ID do usuário Sistema
    cursor.execute("SELECT id FROM usuarios WHERE nome = 'Sistema'")
    id_usuario_sistema = cursor.fetchone()[0]
    
    # Obter alguns IDs de produtos para criar movimentações
    cursor.execute("SELECT id FROM produtos WHERE controla_estoque = 1 LIMIT 5")
    produtos_ids = [row[0] for row in cursor.fetchall()]
       
    # Log de auditoria para criação do banco V2
    cursor.execute('''
        INSERT INTO logs_auditoria (acao, descricao)
        VALUES (?, ?)
    ''', ('SETUP_V2', 'Banco de dados V2.0 criado com sucesso - Kardex habilitado'))
    
    conn.commit()
    print("\n✅ Todos os dados iniciais foram inseridos com sucesso!")


def verificar_integridade(conn):
    """Verifica a integridade e exibe estatísticas do banco."""
    cursor = conn.cursor()
    
    print("\n📊 Verificando integridade e estatísticas do banco...")
    
    # Contar registros nas principais tabelas
    tabelas = [
        'unidades_medida', 'usuarios', 'setores', 'locais', 
        'produtos', 'produtos_unidades', 'inventarios', 
        'movimentacoes', 'configs', 'categorias_inventario',
        'produto_categoria_inventario'
    ]
    
    print("\n📈 Estatísticas:")
    for tabela in tabelas:
        cursor.execute(f'SELECT COUNT(*) FROM {tabela}')
        count = cursor.fetchone()[0]
        print(f"  - {tabela}: {count} registros")
    
    # Estoque total valorizado
    cursor.execute('''
        SELECT SUM(estoque_atual * preco_custo) 
        FROM produtos 
        WHERE controla_estoque = 1
    ''')
    estoque_total = cursor.fetchone()[0] or 0
    print(f"\n  💰 Estoque total valorizado: R$ {estoque_total:,.2f}")
    
    print("\n✅ Verificação de integridade concluída!")


def main():
    """Função principal que executa o setup completo."""
    print("=" * 70)
    print("   SETUP DO BANCO DE DADOS - VERSÃO 2.0")
    print("   SISTEMA DE CONTAGEM DE ESTOQUE PADARIA")
    print("   🆕 Agora com Kardex, Curva ABC e Controle de Estoque")
    print("=" * 70)
    
    # Remove o banco existente se houver (para recriar do zero)
    if os.path.exists(DB_PATH):
        backup_path = DB_PATH.replace('.db', '_backup_v1.db')
        try:
            os.rename(DB_PATH, backup_path)
            print(f"✓ Backup da V1 criado: {backup_path}")
        except:
            os.remove(DB_PATH)
            print(f"✓ Banco de dados antigo removido: {DB_PATH}")
    
    # Conecta ao banco (cria se não existir)
    conn = sqlite3.connect(DB_PATH)
    print(f"✓ Conectado ao banco: {DB_PATH}")
    
    try:
        # Cria as tabelas
        criar_tabelas(conn)
        
        # Insere dados iniciais
        inserir_dados_iniciais(conn)
        
        # Verifica integridade
        verificar_integridade(conn)
        
        print("\n" + "=" * 70)
        print("✅ SETUP V2.0 CONCLUÍDO COM SUCESSO!")
        print("=" * 70)
        print("\n🎯 Próximos passos:")
        print("  1. Testar o sistema com os dados de exemplo")
        print("  2. Implementar as funções de cálculo de Curva ABC")
        print("  3. Criar endpoints para visualizar o Kardex (movimentacoes)")
        print("  4. Implementar ajuste de estoque pós-inventário")
        print("\n📚 Documentação das novas tabelas:")
        print("  - movimentacoes: Extrato completo de entradas/saídas")
        print("  - configs: Parametrizações do sistema")
        print("  - produtos: Agora com estoque_atual, curva_abc, abc_fixo, controla_estoque")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ ERRO durante o setup: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
