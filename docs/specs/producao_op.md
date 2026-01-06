# Especificação: Saída para Produção (Ordem de Produção)

Objetivo: controlar consumo de insumos por OP, comparando previsto (BOM/receita) vs real, com backflush opcional, registro de yield e variâncias.

## Fluxo
- Criar OP: produto acabado, quantidade planejada, datas, origem e observação.
- Importar/definir BOM: insumos previstos (produto, quantidade, unidade).
- Registrar consumo real: itens consumidos, unidade, conversão; motivos de variância (quebra, sucata, ajuste).
- Finalizar: gera movimentações de SAÍDA de insumos; opcionalmente, registra ENTRADA do produto acabado (acabamento) conforme política.

## Modelo de Dados
Tabela `ordens_producao`:
- id INTEGER PK
- produto_acabado_id INTEGER REFERENCES produtos(id) NOT NULL
- quantidade_planejada REAL CHECK (quantidade_planejada > 0) NOT NULL
- data_inicio TEXT ISO NULL
- data_fim TEXT ISO NULL
- status TEXT CHECK ('RASCUNHO','FINALIZADA','CANCELADA') DEFAULT 'RASCUNHO'
- origem TEXT NULL
- observacao TEXT NULL
- id_usuario INTEGER REFERENCES usuarios(id)
- data_criacao TEXT ISO NOT NULL
- data_finalizacao TEXT ISO NULL

Índices: (status), (produto_acabado_id, status).

Tabela `consumo_producao_itens`:
- id INTEGER PK
- id_ordem_producao INTEGER REFERENCES ordens_producao(id) ON DELETE CASCADE
- id_produto INTEGER REFERENCES produtos(id) NOT NULL  // insumo
- quantidade_prevista REAL NULL
- quantidade_real REAL CHECK (quantidade_real >= 0) NULL
- unidade_movimentacao TEXT NULL
- fator_conversao REAL CHECK (fator_conversao > 0) DEFAULT 1.0
- motivo_variancia TEXT NULL
- created_at TEXT ISO NOT NULL

Índices: (id_ordem_producao), (id_produto, id_ordem_producao).

## Endpoints (Admin)
- POST `/admin/producao/op/iniciar` → cria OP rascunho.
- GET `/admin/producao/op/<id>` → detalhes, BOM e consumos.
- POST `/admin/producao/op/<id>/bom/item` → adiciona previsto.
- POST `/admin/producao/op/<id>/consumo/item` → adiciona consumo real.
- PUT `/admin/producao/op/<id>/consumo/item/<item_id>` → edita.
- DELETE `/admin/producao/op/<id>/consumo/item/<item_id>` → remove.
- POST `/admin/producao/op/<id>/finalizar` → valida e gera movimentações de SAÍDA dos insumos; opcional ENTRADA do acabado.

## UX (Wireframe descritivo)
- Cabeçalho da OP: produto acabado, quantidade planejada, datas.
- Duas colunas: previsto (BOM) vs real; totais e variâncias por item e total.
- Busca, teclado numérico, conversão de unidades.
- Finalização com resumo e logs.
