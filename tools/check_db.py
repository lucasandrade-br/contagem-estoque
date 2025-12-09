import sqlite3
conn = sqlite3.connect('database/padaria.db')
cur = conn.cursor()
print('USUARIOS:')
rows = cur.execute('SELECT id, nome, funcao, senha, ativo FROM usuarios').fetchall()
for r in rows:
    print(r)
print('\nTABLE SQL:')
res = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone()
print(res[0] if res else 'N/A')
conn.close()
