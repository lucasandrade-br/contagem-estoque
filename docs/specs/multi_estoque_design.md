# Design: Sistema de Multi-Estoque com 3 Níveis

## Objetivo
Permitir que o sistema opere em 3 modalidades de controle de estoque, configurável pelo usuário conforme a necessidade e complexidade da operação.

---

## Modalidades de Controle

### 1. CENTRAL (Padrão - Como está hoje)
**Para quem**: Empresas pequenas, operação simples, poucos produtos.

**Como funciona**:
- Um único estoque centralizado
- Não rastreia localização física
- Entrada/saída/transferência não perguntam setor ou local
- Relatório mostra apenas totais globais por produto

**Exemplo**:
- "Recebi 100 parafusos" → vai para estoque central
- "Vendi 30 parafusos" → sai do estoque central
- Transferência não se aplica (tudo está no mesmo lugar lógico)

---

### 2. SETOR (Controle por Área)
**Para quem**: Empresas médias, áreas bem definidas, controle intermediário.

**Como funciona**:
- Estoque dividido por SETORES (Almoxarifado, Produção, Expedição, etc.)
- Entrada/saída pedem o SETOR envolvido
- Transferência move entre setores
- Relatório mostra totais por setor e total geral

**Exemplo**:
- "Recebi 100 parafusos" → escolhe SETOR (Almoxarifado)
- "Consumiu 30 parafusos" → escolhe SETOR origem (Produção)
- "Transferiu 20 parafusos" → de Almoxarifado para Produção

**Benefício**: Sabe ONDE está (em qual área), sem detalhamento excessivo.

---

### 3. LOCAL (Controle Detalhado)
**Para quem**: Empresas grandes, muito estoque, necessidade de precisão máxima.

**Como funciona**:
- Estoque dividido por SETOR → LOCAL (Almoxarifado → Prateleira A)
- Entrada/saída pedem SETOR e depois o LOCAL específico
- Transferência move entre locais (pode ser do mesmo setor ou não)
- Relatório mostra totais por local, por setor e total geral

**Exemplo**:
- "Recebi 100 parafusos" → Almoxarifado → Prateleira A
- "Consumiu 30 parafusos" → Produção → Bancada 2
- "Transferiu 20 parafusos" → de Almoxarifado/Prateleira A para Produção/Bancada 2

**Benefício**: Precisão máxima; sabe exatamente em qual móvel/endereço está cada produto.

---

## Configuração do Sistema

### Tabela `configs`
Nova entrada:
```sql
INSERT INTO configs (chave, valor, descricao) 
VALUES ('NIVEL_CONTROLE_ESTOQUE', 'CENTRAL', 'Nível de controle: CENTRAL, SETOR ou LOCAL');
```

**Valores possíveis**:
- `'CENTRAL'` = sem localização (modo atual)
- `'SETOR'` = controle por setor
- `'LOCAL'` = controle por setor + local

---

## Tipos de Movimentação

### ENTRADA
- **CENTRAL**: sem origem/destino
- **SETOR**: exige `setor_destino_id`
- **LOCAL**: exige `setor_destino_id` + `local_destino_id`

### SAÍDA
- **CENTRAL**: sem origem/destino
- **SETOR**: exige `setor_origem_id`
- **LOCAL**: exige `setor_origem_id` + `local_origem_id`

### TRANSFERÊNCIA (novo tipo!)
- **CENTRAL**: não se aplica (tudo está no mesmo lugar)
- **SETOR**: exige `setor_origem_id` + `setor_destino_id`
- **LOCAL**: exige `setor_origem_id` + `local_origem_id` + `setor_destino_id` + `local_destino_id`

**Características da Transferência**:
- Não altera estoque total da empresa
- Movimenta apenas a localização
- Valor financeiro neutro (mantém custo médio)
- Gera duas linhas lógicas: SAÍDA da origem + ENTRADA no destino, ou uma linha com ambos

---

## Modelo de Dados

### Tabela `estoque_saldos`
Armazena saldo por produto e localização conforme nível configurado.

```sql
CREATE TABLE estoque_saldos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  produto_id INTEGER NOT NULL,
  setor_id INTEGER,         -- null se NIVEL = CENTRAL
  local_id INTEGER,          -- null se NIVEL != LOCAL
  saldo REAL NOT NULL DEFAULT 0,
  FOREIGN KEY (produto_id) REFERENCES produtos(id),
  FOREIGN KEY (setor_id) REFERENCES setores(id),
  FOREIGN KEY (local_id) REFERENCES locais(id),
  UNIQUE(produto_id, setor_id, local_id)
);
```

**Como funciona**:
- CENTRAL: `(produto_id=1, setor_id=NULL, local_id=NULL, saldo=100)`
- SETOR: `(produto_id=1, setor_id=5, local_id=NULL, saldo=50)`
- LOCAL: `(produto_id=1, setor_id=5, local_id=12, saldo=30)`

### Tabela `movimentacoes` (adicionar campos)
```sql
ALTER TABLE movimentacoes ADD COLUMN setor_origem_id INTEGER;
ALTER TABLE movimentacoes ADD COLUMN local_origem_id INTEGER;
ALTER TABLE movimentacoes ADD COLUMN setor_destino_id INTEGER;
ALTER TABLE movimentacoes ADD COLUMN local_destino_id INTEGER;
```

### Tabela `lotes_movimentacao` (adicionar campos)
```sql
ALTER TABLE lotes_movimentacao ADD COLUMN setor_origem_id INTEGER;
ALTER TABLE lotes_movimentacao ADD COLUMN local_origem_id INTEGER;
ALTER TABLE lotes_movimentacao ADD COLUMN setor_destino_id INTEGER;
ALTER TABLE lotes_movimentacao ADD COLUMN local_destino_id INTEGER;
```

---

## Regras de Validação

### Por Nível
1. **CENTRAL**: origem/destino sempre NULL
2. **SETOR**: origem/destino setor obrigatório; local sempre NULL
3. **LOCAL**: origem/destino setor E local obrigatórios

### Estoque Negativo
- Validação por nível configurado
- CENTRAL: valida `produtos.estoque_atual`
- SETOR: valida saldo do setor
- LOCAL: valida saldo do local específico

### Transferência
- Origem e destino devem ser diferentes
- Se SETOR: `setor_origem != setor_destino`
- Se LOCAL: `(setor_origem, local_origem) != (setor_destino, local_destino)`

---

## Interface do Usuário

### Cabeçalho do Lote
```
Tipo: [ENTRADA | SAÍDA | TRANSFERÊNCIA]

# Se config = SETOR ou LOCAL:
┌── SE ENTRADA OU SAÍDA ───────────┐
│ Setor: [dropdown]                 │
│ Local: [dropdown] (só se LOCAL)   │
└──────────────────────────────────┘

# Se TRANSFERÊNCIA:
┌── ORIGEM ────────────────────────┐
│ Setor: [dropdown]                 │
│ Local: [dropdown] (só se LOCAL)   │
└──────────────────────────────────┘

┌── DESTINO ───────────────────────┐
│ Setor: [dropdown]                 │
│ Local: [dropdown] (só se LOCAL)   │
└──────────────────────────────────┘
```

### Relatório de Estoque
```
# Config = CENTRAL
┌────────────────────────────────┐
│ Produto      | Qtd Total       │
│ Parafuso M8  | 500 un          │
└────────────────────────────────┘

# Config = SETOR
┌────────────────────────────────────┐
│ Produto      | Setor       | Qtd   │
│ Parafuso M8  | Almoxarifado| 300   │
│ Parafuso M8  | Produção    | 150   │
│ Parafuso M8  | Expedição   | 50    │
│              | TOTAL       | 500   │
└────────────────────────────────────┘

# Config = LOCAL
┌───────────────────────────────────────────┐
│ Produto     | Setor       | Local   | Qtd │
│ Parafuso M8 | Almoxarifado| Prat A  | 200 │
│ Parafuso M8 | Almoxarifado| Prat B  | 100 │
│ Parafuso M8 | Produção    | Banc 1  | 150 │
│ Parafuso M8 | Expedição   | Arm 1   | 50  │
│             |             | TOTAL   | 500 │
└───────────────────────────────────────────┘
```

---

## Migração de Nível

### De CENTRAL para SETOR
1. Criar registros em `estoque_saldos` com `setor_id` padrão (ex: "Estoque Geral")
2. Copiar `produtos.estoque_atual` → `estoque_saldos.saldo`
3. Atualizar config para `'SETOR'`

### De SETOR para LOCAL
1. Criar registros em `estoque_saldos` com `local_id` padrão dentro de cada setor
2. Copiar saldos de setor para local padrão
3. Atualizar config para `'LOCAL'`

### De Nível Maior para Menor (downgrade)
- Consolidar saldos (somar locais → setor, somar setores → central)
- Manter histórico de movimentações (não apagar origem/destino)

---

## Próximos Passos
1. ✅ Design conceitual aprovado
2. ⏳ Atualizar migration SQL com novos campos
3. ⏳ Implementar endpoints de lote com suporte aos 3 níveis
4. ⏳ Criar tela de configuração de nível
5. ⏳ Adaptar UI de lote para renderizar campos conforme config
6. ⏳ Implementar relatório "Estoque por Localização"
