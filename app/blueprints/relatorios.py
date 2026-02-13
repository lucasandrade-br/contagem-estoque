from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify
from ..db import get_db

bp = Blueprint('relatorios', __name__)


def _parse_date(value, default=None):
	if not value:
		return default
	try:
		return datetime.strptime(value, "%Y-%m-%d").date()
	except ValueError:
		return default


def _ultimo_snapshot_por_periodo(db, inicio, fim, categoria_id=None):
	"""Retorna snapshot (valor_total) do último dia disponível no intervalo, filtrando categoria se fornecida."""
	filtros = ['data_ref BETWEEN ? AND ?']
	params = [inicio.isoformat(), fim.isoformat()]
	join_categoria = ''

	if categoria_id:
		join_categoria = 'JOIN produto_categoria_inventario pci ON pci.id_produto = sh.produto_id'
		filtros.append('pci.id_categoria = ?')
		params.append(categoria_id)

	where_sql = ' AND '.join(filtros)

	row = db.execute(
		f'''
		SELECT sh.data_ref, SUM(sh.valor_total) as valor
		FROM saldos_historico sh
		{join_categoria}
		WHERE {where_sql}
		GROUP BY sh.data_ref
		ORDER BY sh.data_ref DESC
		LIMIT 1
		''',
		params
	).fetchone()
	return (row['data_ref'], float(row['valor'])) if row else (None, 0.0)


def _snapshot_em(db, data_ref, categoria_id=None):
	filtros = ['data_ref = ?']
	params = [data_ref.isoformat()]
	join_categoria = ''

	if categoria_id:
		join_categoria = 'JOIN produto_categoria_inventario pci ON pci.id_produto = sh.produto_id'
		filtros.append('pci.id_categoria = ?')
		params.append(categoria_id)

	where_sql = ' AND '.join(filtros)

	row = db.execute(
		f'''
		SELECT SUM(sh.valor_total) as valor
		FROM saldos_historico sh
		{join_categoria}
		WHERE {where_sql}
		''',
		params
	).fetchone()
	return float(row['valor'] or 0.0)


def _cmv_movtos(db, data_inicio, data_fim, categoria_id=None):
	filtros = ['DATE(m.data_movimento) BETWEEN ? AND ?']
	params = [data_inicio.isoformat(), data_fim.isoformat()]

	if categoria_id:
		filtros.append('pci.id_categoria = ?')
		params.append(categoria_id)

	where_sql = ' AND '.join(filtros)

	row = db.execute(
		f'''
		SELECT 
			COALESCE(SUM(CASE WHEN m.tipo = 'SAIDA' THEN ABS(m.valor_total) ELSE 0 END), 0) as cmv,
			COALESCE(SUM(CASE WHEN m.tipo = 'ENTRADA' THEN m.valor_total ELSE 0 END), 0) as entradas
		FROM movimentacoes m
		JOIN produtos p ON p.id = m.id_produto
		LEFT JOIN produto_categoria_inventario pci ON pci.id_produto = p.id
		WHERE {where_sql}
		''',
		params
	).fetchone()

	return float(row['cmv'] or 0.0), float(row['entradas'] or 0.0)


def _estoque_por_inventario(db, inventario_id, categoria_id=None):
	"""Calcula o valor do estoque a partir de uma contagem (inventário) específica."""
	filtros = ['c.id_inventario = ?']
	params = [inventario_id]
	join_categoria = ''

	if categoria_id:
		join_categoria = 'JOIN produto_categoria_inventario pci ON pci.id_produto = p.id'
		filtros.append('pci.id_categoria = ?')
		params.append(categoria_id)

	where_sql = ' AND '.join(filtros)

	row = db.execute(
		f'''
		SELECT 
			COALESCE(SUM(c.quantidade_padrao), 0) AS quantidade_total,
			COALESCE(SUM(c.quantidade_padrao * COALESCE(c.preco_custo_snapshot, 0)), 0) AS valor_total
		FROM contagens c
		JOIN inventarios i ON i.id = c.id_inventario
		JOIN produtos p ON p.id = c.id_produto
		{join_categoria}
		WHERE {where_sql} AND p.ativo = 1 AND p.controla_estoque = 1
		''',
		params
	).fetchone()

	qtd = float(row['quantidade_total'] or 0.0)
	valor = float(row['valor_total'] or 0.0)
	return qtd, valor


def _series_snapshots(db, data_inicio, data_fim, categoria_id=None, granularidade='semanal'):
	series = []

	if granularidade == 'mensal':
		ano_mes_inicio = (data_inicio.year, data_inicio.month)
		ano_mes_fim = (data_fim.year, data_fim.month)

		ano, mes = ano_mes_inicio
		while (ano, mes) <= ano_mes_fim:
			inicio_mes = date(ano, mes, 1)
			if mes == 12:
				fim_mes_cal = date(ano + 1, 1, 1) - timedelta(days=1)
			else:
				fim_mes_cal = date(ano, mes + 1, 1) - timedelta(days=1)

			inicio_intervalo = max(inicio_mes, data_inicio)
			fim_intervalo = min(fim_mes_cal, data_fim)

			if inicio_intervalo <= fim_intervalo:
				data_snap, valor_snap = _ultimo_snapshot_por_periodo(db, inicio_intervalo, fim_intervalo, categoria_id)
				if data_snap:
					series.append({'data_ref': data_snap, 'valor_total': valor_snap})

			mes += 1
			if mes == 13:
				mes = 1
				ano += 1
	else:
		# semanal (padrão): último snapshot de cada semana
		dia = data_inicio
		while dia <= data_fim:
			fim_semana = dia + timedelta(days=(6 - dia.weekday()))
			if fim_semana > data_fim:
				fim_semana = data_fim
			data_snap, valor_snap = _ultimo_snapshot_por_periodo(db, dia, fim_semana, categoria_id)
			if data_snap:
				series.append({'data_ref': data_snap, 'valor_total': valor_snap})
			dia = fim_semana + timedelta(days=1)

	return series


@bp.route('/relatorios/cmv')
def relatorio_cmv():
	db = get_db()

	# Filtros
	data_inicio = _parse_date(request.args.get('data_inicio'), default=date.today().replace(day=1))
	data_fim = _parse_date(request.args.get('data_fim'), default=date.today())
	categoria_id = request.args.get('categoria_id', type=int)
	granularidade = request.args.get('granularidade', 'semanal')
	inventario_inicio_id = request.args.get('inventario_inicio_id', type=int)
	inventario_fim_id = request.args.get('inventario_fim_id', type=int)

	if data_inicio > data_fim:
		data_inicio, data_fim = data_fim, data_inicio

	# Estoque inicial: snapshot anterior ou inventário selecionado
	if inventario_inicio_id:
		_, estoque_inicial = _estoque_por_inventario(db, inventario_inicio_id, categoria_id)
	else:
		estoque_inicial = _snapshot_em(db, data_inicio - timedelta(days=1), categoria_id)

	# Estoque final: último snapshot até data_fim ou inventário selecionado
	if inventario_fim_id:
		_, estoque_final = _estoque_por_inventario(db, inventario_fim_id, categoria_id)
	else:
		_, estoque_final = _ultimo_snapshot_por_periodo(db, data_inicio, data_fim, categoria_id)

	cmv_movto, entradas = _cmv_movtos(db, data_inicio, data_fim, categoria_id)

	cmv_teorico = estoque_inicial + entradas - estoque_final
	diferenca = cmv_movto - cmv_teorico

	series = _series_snapshots(db, data_inicio, data_fim, categoria_id, granularidade)

	categorias = [
		dict(r) for r in db.execute(
			'SELECT id, nome FROM categorias_inventario WHERE ativo = 1 ORDER BY nome'
		).fetchall()
	]

	inventarios = [
		dict(r) for r in db.execute(
			"""
			SELECT id, descricao, data_criacao, data_fechamento, status
			FROM inventarios
			WHERE DATE(data_criacao) BETWEEN ? AND ?
			ORDER BY DATE(data_criacao) DESC
			""",
			(data_inicio.isoformat(), data_fim.isoformat())
		).fetchall()
	]

	return render_template(
		'admin/relatorio_cmv.html',
		data_inicio=data_inicio,
		data_fim=data_fim,
		categoria_id=categoria_id,
		categorias=categorias,
		inventarios=inventarios,
		granularidade=granularidade,
		inventario_inicio_id=inventario_inicio_id,
		inventario_fim_id=inventario_fim_id,
		estoque_inicial=round(estoque_inicial, 2),
		estoque_final=round(estoque_final, 2),
		entradas=round(entradas, 2),
		cmv_movto=round(cmv_movto, 2),
		cmv_teorico=round(cmv_teorico, 2),
		diferenca=round(diferenca, 2),
		series=series,
		is_gerente=True
	)


@bp.route('/relatorios/cmv.json')
def relatorio_cmv_json():
	db = get_db()

	data_inicio = _parse_date(request.args.get('data_inicio'), default=date.today().replace(day=1))
	data_fim = _parse_date(request.args.get('data_fim'), default=date.today())
	categoria_id = request.args.get('categoria_id', type=int)
	granularidade = request.args.get('granularidade', 'semanal')
	inventario_inicio_id = request.args.get('inventario_inicio_id', type=int)
	inventario_fim_id = request.args.get('inventario_fim_id', type=int)

	cmv_movto, entradas = _cmv_movtos(db, data_inicio, data_fim, categoria_id)
	if inventario_inicio_id:
		_, estoque_inicial = _estoque_por_inventario(db, inventario_inicio_id, categoria_id)
	else:
		estoque_inicial = _snapshot_em(db, data_inicio - timedelta(days=1), categoria_id)

	if inventario_fim_id:
		_, estoque_final = _estoque_por_inventario(db, inventario_fim_id, categoria_id)
	else:
		_, estoque_final = _ultimo_snapshot_por_periodo(db, data_inicio, data_fim, categoria_id)
	cmv_teorico = estoque_inicial + entradas - estoque_final
	diferenca = cmv_movto - cmv_teorico
	series = _series_snapshots(db, data_inicio, data_fim, categoria_id, granularidade)

	return jsonify({
		'data_inicio': data_inicio.isoformat(),
		'data_fim': data_fim.isoformat(),
		'categoria_id': categoria_id,
		'granularidade': granularidade,
		'estoque_inicial': round(estoque_inicial, 2),
		'estoque_final': round(estoque_final, 2),
		'entradas': round(entradas, 2),
		'cmv_movto': round(cmv_movto, 2),
		'cmv_teorico': round(cmv_teorico, 2),
		'diferenca': round(diferenca, 2),
		'series': series
	})
