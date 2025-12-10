"""
Script de setup do banco de dados SQLite para o sistema de Contagem de Estoque Padaria.
Cria todas as tabelas e insere dados iniciais (seed data).
"""

import sqlite3
import os
from datetime import datetime

# Caminho do banco de dados
DB_PATH = os.path.join(os.path.dirname(__file__), 'padaria.db')


def criar_tabelas(conn):
    """Cria todas as tabelas do banco de dados."""
    cursor = conn.cursor()
    
    # 1. Tabela unidades_medida
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unidades_medida (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sigla TEXT NOT NULL UNIQUE,
            nome TEXT NOT NULL,
            permite_decimal BOOLEAN NOT NULL DEFAULT 0
        )
    ''')
    
    # 2. Tabela usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            funcao TEXT NOT NULL CHECK(funcao IN ('Gerente', 'Estoquista', 'Estoquista Chefe')),
            senha TEXT,
            ativo BOOLEAN NOT NULL DEFAULT 1
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
    
    # 5. Tabela produtos (apenas unidade padrão; fatores vão para produtos_unidades)
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
            ativo BOOLEAN DEFAULT 1,
            FOREIGN KEY (id_unidade_padrao) REFERENCES unidades_medida(id)
        )
    ''')
    
    # Criar índice UNIQUE para id_erp (SQLite não suporta UNIQUE em ALTER TABLE)
    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_produtos_id_erp 
        ON produtos(id_erp) WHERE id_erp IS NOT NULL
    ''')
    
    # 5b. Tabela de relacionamento produtos_unidades (N:N) com fator de conversão
    # fator_conversao indica quanto 1 unidade desta unidade representa em relação à unidade padrão do produto.
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
    
    # 6. Tabela inventarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_criacao DATE NOT NULL,
            data_fechamento DATE,
            status TEXT NOT NULL CHECK(status IN ('Aberto', 'Fechado')),
            descricao TEXT
        )
    ''')
    
    # 7. Tabela contagens
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_inventario INTEGER NOT NULL,
            id_produto INTEGER NOT NULL,
            id_local INTEGER NOT NULL,
            id_usuario INTEGER NOT NULL,
            quantidade REAL NOT NULL,
            id_unidade_usada INTEGER NOT NULL,
                   
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
    
    # 8. Tabela logs_auditoria
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs_auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acao TEXT NOT NULL,
            descricao TEXT,
            data_hora DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 9. Tabela ocorrencias (Itens não cadastrados ou avulsos)
    cursor.execute('''
        CREATE TABLE ocorrencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_inventario INTEGER NOT NULL,
            id_local INTEGER NOT NULL,
            id_usuario INTEGER, -- Pode ser NULL se não tiver login forçado no tablet
            nome_identificado TEXT NOT NULL,
            quantidade REAL NOT NULL,
            id_unidade INTEGER NOT NULL,
            foto_path TEXT,
            resolvido INTEGER NOT NULL DEFAULT 0,
            obs TEXT, -- Coluna nova para observações do gerente
            data_hora DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (id_inventario) REFERENCES inventarios(id) ON DELETE CASCADE,
            FOREIGN KEY (id_local) REFERENCES locais(id) ON DELETE CASCADE,
            FOREIGN KEY (id_usuario) REFERENCES usuarios(id) ON DELETE SET NULL,
            FOREIGN KEY (id_unidade) REFERENCES unidades_medida(id)
        )
    ''')
    
    conn.commit()
    print("✓ Todas as tabelas foram criadas com sucesso!")


def inserir_dados_iniciais(conn):
    """Insere dados de teste (seed data) no banco."""
    cursor = conn.cursor()
    
    # Unidades de medida
    unidades = [
        ('KG', 'Quilograma', True),
        ('LT', 'Litro', True),
        ('UN', 'Unidade', False),
        ('CX', 'Caixa', False),
        ('FD', 'Fardo', False)
    ]
    cursor.executemany('''
        INSERT INTO unidades_medida (sigla, nome, permite_decimal)
        VALUES (?, ?, ?)
    ''', unidades)
    print("✓ Unidades de medida inseridas")
    
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
    print("✓ Setores inseridos")
    
    # Buscar IDs dos setores para criar locais
    cursor.execute('SELECT id, nome FROM setores')
    setores_data = cursor.fetchall()
    
    # Locais (2 para cada setor)
    locais = []
    for setor_id, setor_nome in setores_data:
        if setor_nome == 'Cozinha':
            locais.append(('Freezer 1', setor_id, 0))
            locais.append(('Geladeira Principal', setor_id, 0))
        elif setor_nome == 'Loja':
            locais.append(('Prateleira A', setor_id, 0))
            locais.append(('Prateleira B', setor_id, 0))
        elif setor_nome == 'Almoxarifado':
            locais.append(('Estante 1', setor_id, 0))
            locais.append(('Estante 2', setor_id, 0))
    
    cursor.executemany('''
        INSERT INTO locais (nome, id_setor, status)
        VALUES (?, ?, ?)
    ''', locais)
    print("✓ Locais inseridos")
    
    # Usuários
    usuarios = [
        ('Lucas', 'Gerente', '2706', 1),
        ('Marcio', 'Estoquista', None, 1),
        ('Ronalda', 'Estoquista', None, 1),
        ('Carlos Chefe', 'Estoquista Chefe', None, 1)
    ]
    cursor.executemany('''
        INSERT INTO usuarios (nome, funcao, senha, ativo)
        VALUES (?, ?, ?, ?)
    ''', usuarios)
    print("✓ Usuários inseridos")
    
    # Buscar IDs das unidades para criar produtos
    cursor.execute('SELECT id, sigla FROM unidades_medida')
    unidades_data = {sigla: id for id, sigla in cursor.fetchall()}
    
    # Produtos (5 produtos variados)
    produtos = [
        # nome, categoria, id_unidade_padrao
        ('Prod01', 'Ingredientes', unidades_data['KG']),
        ('Prod02', 'Laticínios', unidades_data['LT']),
        ('Prod03', 'Produtos Prontos', unidades_data['UN']),
        ('Prod04', 'Ingredientes', unidades_data['KG']),
        ('Prod05', 'Ingredientes', unidades_data['CX'])
    ]
    cursor.executemany('''
        INSERT INTO produtos (nome, categoria, id_unidade_padrao)
        VALUES (?, ?, ?)
    ''', produtos)
    print("✓ Produtos inseridos")
    
    # Produtos_unidades: cada produto aceita sua unidade padrão (fator 1.0)
    cursor.execute('SELECT id, id_unidade_padrao FROM produtos')
    relacoes = [(prod_id, id_unidade, 1.0) for prod_id, id_unidade in cursor.fetchall()]
    cursor.executemany('''
        INSERT INTO produtos_unidades (id_produto, id_unidade, fator_conversao)
        VALUES (?, ?, ?)
    ''', relacoes)
    print("✓ Relações produtos_unidades inseridas (unidade padrão, fator 1.0)")
    
    # Inventário inicial (Fechado para testar a trava)
    from datetime import date
    cursor.execute('''
        INSERT INTO inventarios (data_criacao, status, descricao)
        VALUES (?, ?, ?)
    ''', (date.today().isoformat(), 'Fechado', 'Inventário inicial de teste'))
    print("✓ Inventário inicial inserido (status: Fechado)")
    
    conn.commit()
    print("\n✓ Todos os dados iniciais foram inseridos com sucesso!")


def main():
    """Função principal que executa o setup completo."""
    print("=" * 60)
    print("SETUP DO BANCO DE DADOS - CONTAGEM DE ESTOQUE PADARIA")
    print("=" * 60)
    
    # Remove o banco existente se houver (para recriar do zero)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"✓ Banco de dados antigo removido: {DB_PATH}")
    
    # Conecta ao banco (cria se não existir)
    conn = sqlite3.connect(DB_PATH)
    print(f"✓ Conectado ao banco: {DB_PATH}\n")
    
    try:
        # Cria as tabelas
        criar_tabelas(conn)
        print()
        
        # Insere dados iniciais
        inserir_dados_iniciais(conn)
        
        print("\n" + "=" * 60)
        print("✓ SETUP CONCLUÍDO COM SUCESSO!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ ERRO durante o setup: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()

