import sqlite3
from datetime import datetime

DB_PATH = r"database/database.db"


def garantir_colunas(conn):
    cur = conn.cursor()
    cols = {row[1] for row in cur.execute("PRAGMA table_info(estoque_saldos)")}
    altered = False
    if "valor_total" not in cols:
        cur.execute("ALTER TABLE estoque_saldos ADD COLUMN valor_total REAL NOT NULL DEFAULT 0.0")
        altered = True
    if "custo_medio" not in cols:
        cur.execute("ALTER TABLE estoque_saldos ADD COLUMN custo_medio REAL NOT NULL DEFAULT 0.0")
        altered = True
    if altered:
        conn.commit()


def zerar_saldos(conn):
    cur = conn.cursor()
    cur.execute("UPDATE estoque_saldos SET saldo = 0, valor_total = 0, custo_medio = 0")
    conn.commit()


def obter_nivel_controle(conn):
    cur = conn.cursor()
    row = cur.execute("SELECT valor FROM configs WHERE chave = 'NIVEL_CONTROLE_ESTOQUE'").fetchone()
    if row and row[0] in ("CENTRAL", "SETOR", "LOCAL"):
        return row[0]
    return "CENTRAL"


def normalizar_localizacao(nivel, setor_id, local_id):
    if nivel == "CENTRAL":
        return None, None
    if nivel == "SETOR":
        return setor_id, None
    return setor_id, local_id


def obter_posicao(conn, nivel, produto_id, setor_id=None, local_id=None):
    cur = conn.cursor()
    if nivel == "CENTRAL":
        row = cur.execute(
            """SELECT COALESCE(SUM(saldo),0) AS saldo, COALESCE(SUM(valor_total),0) AS valor_total
                   FROM estoque_saldos WHERE produto_id=?""",
            (produto_id,)
        ).fetchone()
        saldo = float(row[0] or 0)
        valor_total = float(row[1] or 0)
        custo_medio = (valor_total / saldo) if saldo > 0 else 0.0
        return saldo, valor_total, custo_medio
    row = cur.execute(
        """SELECT saldo, valor_total, custo_medio FROM estoque_saldos
               WHERE produto_id=? AND setor_id IS ? AND local_id IS ?""",
        (produto_id, setor_id, local_id)
    ).fetchone()
    saldo = float(row[0] or 0) if row else 0.0
    valor_total = float(row[1] or 0) if row else 0.0
    custo_medio = float(row[2] or 0) if row else 0.0
    return saldo, valor_total, custo_medio


def upsert_posicao(conn, produto_id, setor_id, local_id, saldo, valor_total, custo_medio):
    cur = conn.cursor()
    existe = cur.execute(
        """SELECT id FROM estoque_saldos
               WHERE produto_id=? AND setor_id IS ? AND local_id IS ?""",
        (produto_id, setor_id, local_id)
    ).fetchone()
    if existe:
        cur.execute(
            """UPDATE estoque_saldos
                   SET saldo=?, valor_total=?, custo_medio=?
                 WHERE produto_id=? AND setor_id IS ? AND local_id IS ?""",
            (saldo, valor_total, custo_medio, produto_id, setor_id, local_id)
        )
    else:
        cur.execute(
            """INSERT INTO estoque_saldos (produto_id, setor_id, local_id, saldo, valor_total, custo_medio)
                   VALUES (?, ?, ?, ?, ?, ?)""",
            (produto_id, setor_id, local_id, saldo, valor_total, custo_medio)
        )


def reprocessar_movimentacoes(conn):
    nivel = obter_nivel_controle(conn)
    cur = conn.cursor()
    movs = cur.execute(
        """SELECT id, id_produto, tipo, quantidade, preco_custo_unitario,
                      setor_origem_id, local_origem_id, setor_destino_id, local_destino_id, data_movimento
               FROM movimentacoes
               ORDER BY data_movimento ASC, id ASC"""
    ).fetchall()

    total = len(movs)
    for idx, m in enumerate(movs, start=1):
        tipo = m[2]
        qtd = float(m[3] or 0)
        preco = float(m[4] or 0)
        setor_origem = m[5]
        local_origem = m[6]
        setor_dest = m[7]
        local_dest = m[8]

        if tipo == 'ENTRADA':
            setor_id, local_id = normalizar_localizacao(nivel, setor_dest, local_dest)
            saldo, valor_total, custo_medio = obter_posicao(conn, nivel, m[1], setor_id, local_id)
            novo_valor = valor_total + (qtd * preco)
            novo_saldo = saldo + qtd
            novo_custo = (novo_valor / novo_saldo) if novo_saldo > 0 else 0.0
            upsert_posicao(conn, m[1], setor_id, local_id, novo_saldo, novo_valor, novo_custo)

        elif tipo == 'SAIDA':
            setor_id, local_id = normalizar_localizacao(nivel, setor_origem, local_origem)
            saldo, valor_total, custo_medio = obter_posicao(conn, nivel, m[1], setor_id, local_id)
            custo_mov = custo_medio
            novo_valor = valor_total - (qtd * custo_mov)
            novo_saldo = saldo - qtd
            if novo_saldo <= 0:
                novo_valor = 0.0
                novo_custo = 0.0
            else:
                novo_custo = (novo_valor / novo_saldo)
            upsert_posicao(conn, m[1], setor_id, local_id, novo_saldo, novo_valor, novo_custo)

        elif tipo == 'TRANSFERENCIA':
            # SAIDA origem
            setor_id_o, local_id_o = normalizar_localizacao(nivel, setor_origem, local_origem)
            saldo_o, valor_total_o, custo_medio_o = obter_posicao(conn, nivel, m[1], setor_id_o, local_id_o)
            custo_mov = custo_medio_o
            novo_valor_o = valor_total_o - (qtd * custo_mov)
            novo_saldo_o = saldo_o - qtd
            if novo_saldo_o <= 0:
                novo_valor_o = 0.0
                novo_custo_o = 0.0
            else:
                novo_custo_o = (novo_valor_o / novo_saldo_o)
            upsert_posicao(conn, m[1], setor_id_o, local_id_o, novo_saldo_o, novo_valor_o, novo_custo_o)

            # ENTRADA destino com mesmo custo
            setor_id_d, local_id_d = normalizar_localizacao(nivel, setor_dest, local_dest)
            saldo_d, valor_total_d, custo_medio_d = obter_posicao(conn, nivel, m[1], setor_id_d, local_id_d)
            novo_valor_d = valor_total_d + (qtd * custo_mov)
            novo_saldo_d = saldo_d + qtd
            novo_custo_d = (novo_valor_d / novo_saldo_d) if novo_saldo_d > 0 else 0.0
            upsert_posicao(conn, m[1], setor_id_d, local_id_d, novo_saldo_d, novo_valor_d, novo_custo_d)

        else:
            # Tipo inesperado
            pass

        if idx % 1000 == 0:
            conn.commit()
            print(f"Processadas {idx}/{total} movimentações...")

    conn.commit()
    print(f"Reprocessamento concluído: {total} movimentações.")


def main():
    print(f"Início: {datetime.now().isoformat()}")
    conn = sqlite3.connect(DB_PATH)
    garantir_colunas(conn)
    zerar_saldos(conn)
    reprocessar_movimentacoes(conn)
    print(f"Fim: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
