# Especificação: Movimentação em Lote

Objetivo: permitir entradas/saídas/transferências em lote com alta produtividade, mantendo revisão segura em rascunho e impacto no estoque apenas na finalização. Suporta 3 níveis de controle: CENTRAL (sem localização), SETOR (por área) e LOCAL (detalhado por móvel).

## Fluxo
- Iniciar lote: cabeçalho com `tipo` (ENTRADA/SAIDA/TRANSFERENCIA), `motivo`, localização conforme nível configurado, `origem` (opcional), `observacao` (opcional).
- Adicionar itens: pesquisa produto (nome/GTIN/ERP), quantidade, unidade de movimentação, fator de conversão automático, custo unitário por item quando `tipo = ENTRADA`.
- Revisar itens em tabela simplificada (editar/remover, mesclar itens iguais opcional).
- Finalizar lote: validações por nível, transação que gera linhas em `movimentacoes` e atualiza `estoque_saldos` (ou `estoque_atual` se CENTRAL). Auditoria vincula cada movimentação ao `id_lote`.

## Modelo de Dados
Tabela `lotes_movimentacao` (cabeçalho):
- id INTEGER PK
- tipo TEXT CHECK ('ENTRADA','SAIDA','TRANSFERENCIA') NOT NULL
- motivo TEXT NOT NULL
- setor_origem_id INTEGER NULL REFERENCES setores(id)
- local_origem_id INTEGER NULL REFERENCES locais(id)
- setor_destino_id INTEGER NULL REFERENCES setores(id)
- local_destino_id INTEGER NULL REFERENCES locais(id)
- origem TEXT NULL
- observacao TEXT NULL
- status TEXT CHECK ('RASCUNHO','FINALIZADO') DEFAULT 'RASCUNHO'
- id_usuario INTEGER REFERENCES usuarios(id)
- data_criacao TEXT ISO NOT NULL
- data_finalizacao TEXT ISO NULL
- valor_total_estimado REAL DEFAULT 0

Índices: (status), (tipo), (id_usuario, status), (setor_origem_id), (setor_destino_id).

**Regras de preenchimento conforme config**:
- CENTRAL: todos os campos setor/local NULL
- SETOR + ENTRADA: `setor_destino_id` obrigatório
- SETOR + SAÍDA: `setor_origem_id` obrigatório
- SETOR + TRANSFERÊNCIA: `setor_origem_id` e `setor_destino_id` obrigatórios
- LOCAL: mesmas regras + `local_origem_id`/`local_destino_id` obrigatórios

Tabela `lotes_movimentacao_itens`:
- id INTEGER PK
- id_lote INTEGER REFERENCES lotes_movimentacao(id) ON DELETE CASCADE
- id_produto INTEGER REFERENCES produtos(id) NOT NULL
- quantidade_original REAL CHECK (quantidade_original > 0) NOT NULL
- unidade_movimentacao TEXT NOT NULL
- fator_conversao REAL CHECK (fator_conversao > 0) NOT NULL DEFAULT 1.0
- preco_custo_unitario REAL NULL  // usado em ENTRADA (se não informado, usa custo padrão do produto na finalização)
- observacao TEXT NULL
- created_at TEXT ISO NOT NULL

Índices: (id_lote), (id_produto, id_lote).

Alteração em `movimentacoes`:
- Adicionar coluna opcional `id_lote INTEGER NULL` + índice `(id_lote)` para rastreabilidade.

## Regras
- Estoque só altera na finalização.
- Conversão: `quantidade_convertida = quantidade_original * fator_conversao`.
- ENTRADA: custo unitário por item; se vazio em algum item, utiliza snapshot do produto.
- SAÍDA: respeitar `PERMITIR_ESTOQUE_NEGATIVO` e `controla_estoque` no nível configurado (CENTRAL valida estoque_atual; SETOR valida saldo do setor; LOCAL valida saldo do local).
- TRANSFERÊNCIA: origem e destino devem ser diferentes; não altera estoque total; valor financeiro neutro (mantém custo médio).
- Validações por nível: carregar config `NIVEL_CONTROLE_ESTOQUE` e exigir campos apropriados.

## Endpoints (Admin)
- POST `/admin/lotes/iniciar` → cria cabeçalho rascunho, retorna `{id_lote}`.
- GET `/admin/lotes/<id>` → detalhes cabeçalho e itens.
- POST `/admin/lotes/<id>/item` → adiciona item.
- PUT `/admin/lotes/<id>/item/<item_id>` → edita item.
- DELETE `/admin/lotes/<id>/item/<item_id>` → remove item.
- POST `/admin/lotes/<id>/finalizar` → valida, aplica transação, gera `movimentacoes` via `utils.registrar_movimento` e atualiza `estoque_atual`.

## UX (Wireframe descritivo)
- Cabeçalho: modal simples (tipo/motivo, origem, observação).
- Itens: área de busca (nome/GTIN/ERP, leitor de código de barras), teclado numérico, select de unidade com preview de conversão, custo unitário (se ENTRADA).
- Tabela: produto, quantidade, unidade, convertido (padrão), custo unitário, valor do item, ações editar/remover.
- Rodapé: totais e botão “Finalizar Lote” com resumo.
