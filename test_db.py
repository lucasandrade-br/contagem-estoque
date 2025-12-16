import sqlite3

conn = sqlite3.connect('database/padaria.db')
cursor = conn.cursor()

print("=== GERENTES NO SISTEMA ===")
users = cursor.execute('SELECT id, nome, funcao, senha FROM usuarios WHERE funcao="Gerente"').fetchall()
for u in users:
    print(f'ID: {u[0]}, Nome: {u[1]}, Função: {u[2]}, Senha: {u[3]}')

print("\n=== TESTANDO QUERY DE ESTOQUE ATUAL ===")
try:
    produtos = cursor.execute('''
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
        )
        SELECT 
            p.id,
            p.nome,
            COALESCE(p.estoque_atual, 0) as estoque_atual,
            COALESCE(p.estoque_atual, 0) * COALESCE(p.preco_custo, 0) as valor_total,
            um.ultima_movimentacao,
            um.tipo_ultima_mov
        FROM produtos p
        LEFT JOIN ultima_mov um ON p.id = um.id_produto
        WHERE p.ativo = 1
        LIMIT 5
    ''').fetchall()
    
    print("Primeiros 5 produtos:")
    for p in produtos:
        ult_mov = p[4][:10] if p[4] else 'Sem movimentação'
        tipo_mov = p[5] if p[5] else '-'
        print(f'ID: {p[0]}, Nome: {p[1]}, Estoque: {p[2]:.2f}, Valor Total: R$ {p[3]:.2f}, Última Mov: {ult_mov} ({tipo_mov})')
    
    print("\n✅ Query funcionando corretamente!")
except Exception as e:
    print(f"\n❌ Erro na query: {e}")

conn.close()
