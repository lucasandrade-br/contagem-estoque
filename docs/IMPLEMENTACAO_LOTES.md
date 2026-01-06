# Guia de Implementação: Sistema de Lotes de Movimentação

## Visão Geral
Sistema completo para entradas, saídas e transferências em lote, com suporte a 3 níveis de controle de estoque.

## Arquivos Criados/Modificados

### Backend
✅ **app/utils.py** - Funções helper adicionadas:
- `obter_nivel_controle(db)` - retorna nível configurado (CENTRAL/SETOR/LOCAL)
- `obter_saldo(db, produto_id, setor_id, local_id)` - consulta saldo conforme nível
- `ajustar_saldo(db, produto_id, quantidade, tipo, setor_id, local_id)` - atualiza saldo
- `validar_localizacao(db, tipo, setor_origem_id, ...)` - valida campos obrigatórios por nível

✅ **app/blueprints/lotes.py** - Novo blueprint com endpoints:
- `POST /admin/lotes/iniciar` - cria lote rascunho
- `GET /admin/lotes/<id>` - detalhes do lote e itens
- `POST /admin/lotes/<id>/item` - adiciona item
- `PUT /admin/lotes/<id>/item/<item_id>` - edita item
- `DELETE /admin/lotes/<id>/item/<item_id>` - remove item
- `POST /admin/lotes/<id>/finalizar` - valida e finaliza (impacta estoque)

✅ **app/__init__.py** - Blueprint registrado

### Database
✅ **database/migrations/20260105_schema.sql** - DDL completo:
- Tabela `lotes_movimentacao` com campos de localização
- Tabela `lotes_movimentacao_itens`
- Tabela `estoque_saldos` para saldos por localização
- Campos adicionais em `movimentacoes`
- Config `NIVEL_CONTROLE_ESTOQUE`

### Documentação
✅ **docs/specs/multi_estoque_design.md** - Design detalhado dos 3 níveis
✅ **docs/specs/lote_movimentacao.md** - Spec técnica do módulo de lotes
✅ **docs/specs/recebimento_documento.md** - Spec de recebimento por NF
✅ **docs/specs/producao_op.md** - Spec de ordens de produção

---

## Próximos Passos

### 1. Aplicar Migration
Execute o SQL para criar as novas tabelas:

```powershell
# No terminal PowerShell
cd C:\Users\emanu\Desktop\contagem_estoque
python -c "from app.db import get_db; from flask import Flask; app = Flask(__name__); app.config['DATABASE'] = 'database/padaria.db'; with app.app_context(): db = get_db(); db.executescript(open('database/migrations/20260105_schema.sql', encoding='utf-8').read()); db.commit(); print('Migration aplicada!')"
```

### 2. Configurar Nível de Controle
No banco de dados, a config já vem como `'CENTRAL'` (padrão). Para mudar:

```sql
-- Para controle por SETOR:
UPDATE configs SET valor = 'SETOR' WHERE chave = 'NIVEL_CONTROLE_ESTOQUE';

-- Para controle por LOCAL:
UPDATE configs SET valor = 'LOCAL' WHERE chave = 'NIVEL_CONTROLE_ESTOQUE';
```

### 3. Testar Endpoints via Postman/Insomnia

**Iniciar Lote (ENTRADA no modo SETOR)**
```http
POST /admin/lotes/iniciar
Content-Type: application/json

{
  "tipo": "ENTRADA",
  "motivo": "COMPRA",
  "setor_destino_id": 1,
  "origem": "Fornecedor ABC - NF 12345",
  "observacao": "Entrega completa"
}
```

**Adicionar Item**
```http
POST /admin/lotes/1/item
Content-Type: application/json

{
  "id_produto": 5,
  "quantidade_original": 100,
  "unidade_movimentacao": "UN",
  "fator_conversao": 1.0,
  "preco_custo_unitario": 2.50
}
```

**Finalizar Lote**
```http
POST /admin/lotes/1/finalizar
```

### 4. Criar UI (Frontend)

#### Template Base: `templates/admin/lote_novo.html`
Deve:
- Carregar `NIVEL_CONTROLE_ESTOQUE` via endpoint ou contexto
- Renderizar campos setor/local conforme nível
- Reutilizar componentes de busca/teclado de `contagem.html`
- Mostrar tabela de itens com totais
- Botão "Finalizar Lote" com confirmação

#### Exemplo de Lógica JS:
```javascript
// Carregar nível ao abrir página
fetch('/api/config/nivel_controle')
  .then(r => r.json())
  .then(data => {
    const nivel = data.nivel; // 'CENTRAL', 'SETOR' ou 'LOCAL'
    
    if (nivel === 'CENTRAL') {
      // Ocultar todos os campos de localização
    } else if (nivel === 'SETOR') {
      // Mostrar dropdown de setor
    } else if (nivel === 'LOCAL') {
      // Mostrar dropdown de setor + local
    }
  });
```

### 5. Adicionar Endpoint de Config (Opcional)
Em `app/blueprints/api.py`:

```python
@bp.route('/config/nivel_controle')
def api_nivel_controle():
    from ..utils import obter_nivel_controle
    db = get_db()
    nivel = obter_nivel_controle(db)
    return jsonify({'nivel': nivel})
```

### 6. Link no Dashboard
Em `templates/admin/dashboard.html`, adicionar botão:

```html
<a href="{{ url_for('admin.lote_novo') }}" 
   class="bg-amber-500 hover:bg-amber-600 text-slate-900 font-bold px-6 py-3 rounded-lg">
    📦 Nova Movimentação em Lote
</a>
```

---

## Fluxo de Uso

1. **Gerente acessa "Nova Movimentação em Lote"**
2. **Seleciona tipo** (ENTRADA/SAÍDA/TRANSFERÊNCIA)
3. **Informa localização** (conforme nível configurado)
4. **Adiciona produtos rapidamente** (como na contagem)
   - Busca por nome/código
   - Teclado numérico
   - Unidade com conversão automática
   - Custo unitário (se ENTRADA)
5. **Revisa itens na tabela**
   - Editar/remover antes de finalizar
   - Ver totais e valor estimado
6. **Finaliza lote** → estoque é atualizado

---

## Validações Implementadas

✅ Localização obrigatória conforme nível  
✅ Estoque negativo bloqueado (respeitando config)  
✅ Transferência exige origem ≠ destino  
✅ Apenas lotes em RASCUNHO podem ser editados  
✅ Conversão de unidades automática  
✅ Auditoria completa (logs e id_lote em movimentações)

---

## Melhorias Futuras

- UI de lote (template HTML + JS)
- Relatório "Estoque por Localização"
- Endpoint de listagem de lotes (histórico)
- Suporte a anexos (NF, fotos)
- Recebimento por documento (módulo avançado)
- Ordens de produção (módulo avançado)

---

## Comandos Úteis

**Consultar nível configurado:**
```sql
SELECT valor FROM configs WHERE chave = 'NIVEL_CONTROLE_ESTOQUE';
```

**Ver saldos por localização:**
```sql
SELECT p.nome, s.nome as setor, l.nome as local, es.saldo
FROM estoque_saldos es
JOIN produtos p ON es.produto_id = p.id
LEFT JOIN setores s ON es.setor_id = s.id
LEFT JOIN locais l ON es.local_id = l.id
ORDER BY p.nome, s.nome, l.nome;
```

**Ver movimentações de um lote:**
```sql
SELECT m.*, p.nome as produto
FROM movimentacoes m
JOIN produtos p ON m.id_produto = p.id
WHERE m.id_lote = 1;
```

---

## Suporte

Para dúvidas ou problemas:
1. Verificar logs no console (`traceback.print_exc()` ativo)
2. Consultar specs em `docs/specs/`
3. Validar migration aplicada
4. Conferir nível configurado
