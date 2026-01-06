# Especificação: Recebimento por Documento

Objetivo: registrar entradas de mercadorias agrupadas por documento (NF/Pedido), com custo unitário por item, anexos e revisão antes do impacto no estoque.

## Fluxo
- Criar documento: fornecedor, número/documento, data, origem (opcional), observação (opcional), anexos.
- Adicionar itens: produto, quantidade, unidade, fator de conversão, custo unitário por item.
- Conferir: permitir recebimento parcial; marcar itens conferidos; ver totais e valores.
- Finalizar: gera movimentações de ENTRADA, atualiza `estoque_atual`, registra auditoria, vincula cada movimentação ao `id_documento` (opcional) e/ou `id_lote` se consolidar via lote.

## Modelo de Dados
Tabela `documentos_recebimento`:
- id INTEGER PK
- fornecedor_nome TEXT NULL
- fornecedor_id TEXT NULL
- numero_documento TEXT NULL
- data_documento TEXT ISO NULL
- origem TEXT NULL
- observacao TEXT NULL
- status TEXT CHECK ('RASCUNHO','FINALIZADO') DEFAULT 'RASCUNHO'
- id_usuario INTEGER REFERENCES usuarios(id)
- anexos_json TEXT NULL  // lista de caminhos
- data_criacao TEXT ISO NOT NULL
- data_finalizacao TEXT ISO NULL

Índices: (status), (numero_documento), (id_usuario, status).

Tabela `documentos_recebimento_itens`:
- id INTEGER PK
- id_documento INTEGER REFERENCES documentos_recebimento(id) ON DELETE CASCADE
- id_produto INTEGER REFERENCES produtos(id) NOT NULL
- quantidade_original REAL CHECK (quantidade_original > 0) NOT NULL
- unidade_movimentacao TEXT NOT NULL
- fator_conversao REAL CHECK (fator_conversao > 0) NOT NULL DEFAULT 1.0
- preco_custo_unitario REAL NOT NULL
- observacao TEXT NULL
- conferido INTEGER CHECK (conferido IN (0,1)) DEFAULT 0
- created_at TEXT ISO NOT NULL

Índices: (id_documento), (id_produto, id_documento).

## Endpoints (Admin)
- POST `/admin/recebimentos/iniciar` → cria documento rascunho.
- GET `/admin/recebimentos/<id>` → detalhes e itens.
- POST `/admin/recebimentos/<id>/item` → adiciona item com custo unitário.
- PUT `/admin/recebimentos/<id>/item/<item_id>` → edita item.
- PATCH `/admin/recebimentos/<id>/item/<item_id>/conferir` → marca conferido.
- DELETE `/admin/recebimentos/<id>/item/<item_id>` → remove item.
- POST `/admin/recebimentos/<id>/finalizar` → valida e cria movimentações via `utils.registrar_movimento`.

## UX (Wireframe descritivo)
- Cabeçalho: fornecedor/NF/data, anexos, origem/observação.
- Itens: busca rápida, teclado numérico, unidade e conversão, custo unitário por item.
- Tabela: status de conferência por linha, totais e valor total.
- Finalização: resumo + confirmação; bloqueio de estoque negativo não se aplica a ENTRADA.
