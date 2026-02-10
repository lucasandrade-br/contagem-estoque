/**
 * Sistema de Lotes de Movimentação - Otimizado para Mobile
 * Inspirado em contagem.html com modal e teclado numérico
 */

// Estado Global
const state = {
    loteId: null,
    nivel: null,
    tipo: null,
    setores: [],
    locais: [],
    itens: [],
    produtoSelecionado: null
};

// Opções de Motivo por Tipo (Ajuste 1)
const MOTIVOS = {
    ENTRADA: ['COMPRA', 'DEVOLUÇÃO', 'AJUSTE', 'TRANSFERÊNCIA', 'OUTROS'],
    SAIDA: ['VENDA', 'PRODUÇÃO', 'PERDA', 'AJUSTE', 'TRANSFERÊNCIA', 'OUTROS'],
    TRANSFERENCIA: ['REPOSIÇÃO', 'REORGANIZAÇÃO', 'OUTROS']
};

// ========================================
// INICIALIZAÇÃO
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    carregarConfiguracoes();
    
    // Event Listeners
    document.getElementById('tipo').addEventListener('change', onTipoChange);
    document.getElementById('form-cabecalho').addEventListener('submit', iniciarLote);
    document.getElementById('busca-produto').addEventListener('input', debounce(buscarProduto, 300));
    document.getElementById('form-adicionar-item').addEventListener('submit', adicionarItem);
    document.getElementById('form-editar-item').addEventListener('submit', salvarEdicaoItem);
});

async function carregarConfiguracoes() {
    mostrarLoader();
    
    try {
        // Buscar nível de controle
        const resNivel = await fetch('/api/config/nivel_controle');
        const configNivel = await resNivel.json();
        state.nivel = configNivel.nivel;
        
        // Atualizar UI
        document.getElementById('display-nivel').textContent = state.nivel;
        
        // Carregar setores e locais se necessário
        if (state.nivel === 'SETOR' || state.nivel === 'LOCAL') {
            const resSetores = await fetch('/api/setores');
            state.setores = await resSetores.json();
        }
        
        if (state.nivel === 'LOCAL') {
            const resLocais = await fetch('/api/locais');
            state.locais = await resLocais.json();
        }
        
    } catch (error) {
        console.error('Erro ao carregar configurações:', error);
        alert('Erro ao carregar configurações do sistema');
    } finally {
        ocultarLoader();
    }
}

// ========================================
// FORM CABEÇALHO
// ========================================

function onTipoChange(e) {
    const tipo = e.target.value;
    state.tipo = tipo;
    
    // Atualizar display
    document.getElementById('display-tipo').textContent = tipo || '-';
    
    // Atualizar opções de motivo (Ajuste 1)
    atualizarOpcoesMotivo(tipo);
    
    // Renderizar campos de localização
    renderizarCamposLocalizacao();
}

function atualizarOpcoesMotivo(tipo) {
    const selectMotivo = document.getElementById('motivo');
    selectMotivo.innerHTML = '<option value="">Selecione...</option>';
    
    if (tipo && MOTIVOS[tipo]) {
        MOTIVOS[tipo].forEach(motivo => {
            const option = document.createElement('option');
            option.value = motivo;
            option.textContent = motivo;
            selectMotivo.appendChild(option);
        });
    }
}

function renderizarCamposLocalizacao() {
    const container = document.getElementById('campos-localizacao');
    const tipo = state.tipo;
    const nivel = state.nivel;
    
    if (!tipo || !nivel) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // CENTRAL: sem campos de localização
    if (nivel === 'CENTRAL') {
        container.innerHTML = '';
        return;
    }
    
    // SETOR ou LOCAL
    if (tipo === 'ENTRADA') {
        if (nivel === 'SETOR') {
            html = criarSelectSetor('setor_destino_id', 'Setor Destino *');
        } else if (nivel === 'LOCAL') {
            html = criarSelectSetor('setor_destino_id', 'Setor Destino *');
            html += criarSelectLocal('local_destino_id', 'Local Destino *', 'setor_destino_id');
        }
    } else if (tipo === 'SAIDA') {
        if (nivel === 'SETOR') {
            html = criarSelectSetor('setor_origem_id', 'Setor Origem *');
        } else if (nivel === 'LOCAL') {
            html = criarSelectSetor('setor_origem_id', 'Setor Origem *');
            html += criarSelectLocal('local_origem_id', 'Local Origem *', 'setor_origem_id');
        }
    } else if (tipo === 'TRANSFERENCIA') {
        if (nivel === 'SETOR') {
            html = criarSelectSetor('setor_origem_id', 'Setor Origem *');
            html += criarSelectSetor('setor_destino_id', 'Setor Destino *');
        } else if (nivel === 'LOCAL') {
            html = '<div class="col-span-2"><h3 class="text-gray-300 font-bold mb-2">Origem</h3></div>';
            html += criarSelectSetor('setor_origem_id', 'Setor *');
            html += criarSelectLocal('local_origem_id', 'Local *', 'setor_origem_id');
            
            html += '<div class="col-span-2"><h3 class="text-gray-300 font-bold mb-2 mt-3">Destino</h3></div>';
            html += criarSelectSetor('setor_destino_id', 'Setor *');
            html += criarSelectLocal('local_destino_id', 'Local *', 'setor_destino_id');
        }
    }
    
    container.innerHTML = html;
    
    // Adicionar event listeners para filtrar locais quando setor mudar
    if (nivel === 'LOCAL') {
        const selectsSetor = container.querySelectorAll('select[name^="setor_"]');
        selectsSetor.forEach(select => {
            select.addEventListener('change', () => filtrarLocaisPorSetor(select));
        });
    }
}

function criarSelectSetor(name, label) {
    let html = `<div>
        <label class="block text-gray-300 font-semibold mb-2 text-sm">${label}</label>
        <select name="${name}" id="${name}" required class="w-full p-3 bg-slate-700 text-gray-100 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500">
            <option value="">Selecione...</option>`;
    
    state.setores.forEach(setor => {
        html += `<option value="${setor.id}">${setor.nome}</option>`;
    });
    
    html += `</select></div>`;
    return html;
}

function criarSelectLocal(name, label, setorFieldName) {
    return `<div>
        <label class="block text-gray-300 font-semibold mb-2 text-sm">${label}</label>
        <select name="${name}" id="${name}" required data-setor-field="${setorFieldName}" class="w-full p-3 bg-slate-700 text-gray-100 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500">
            <option value="">Selecione o setor primeiro...</option>
        </select>
    </div>`;
}

function filtrarLocaisPorSetor(selectSetor) {
    const setorId = parseInt(selectSetor.value);
    const name = selectSetor.getAttribute('name');
    const localName = name.replace('setor_', 'local_');
    const selectLocal = document.getElementById(localName);
    
    if (!selectLocal) return;
    
    selectLocal.innerHTML = '<option value="">Selecione...</option>';
    
    if (setorId) {
        const locaisFiltrados = state.locais.filter(l => l.id_setor === setorId);
        locaisFiltrados.forEach(local => {
            const option = document.createElement('option');
            option.value = local.id;
            option.textContent = local.nome;
            selectLocal.appendChild(option);
        });
    }
}

async function iniciarLote(e) {
    e.preventDefault();
    
    mostrarLoader();
    
    const formData = new FormData(e.target);
    const payload = {
        tipo: formData.get('tipo'),
        motivo: formData.get('motivo')
    };
    
    // Adicionar IDs de localização conforme nível
    if (state.nivel !== 'CENTRAL') {
        const tipo = payload.tipo;
        
        if (tipo === 'ENTRADA') {
            if (formData.get('setor_destino_id')) 
                payload.setor_destino_id = parseInt(formData.get('setor_destino_id'));
            if (formData.get('local_destino_id')) 
                payload.local_destino_id = parseInt(formData.get('local_destino_id'));
        } else if (tipo === 'SAIDA') {
            if (formData.get('setor_origem_id')) 
                payload.setor_origem_id = parseInt(formData.get('setor_origem_id'));
            if (formData.get('local_origem_id')) 
                payload.local_origem_id = parseInt(formData.get('local_origem_id'));
        } else if (tipo === 'TRANSFERENCIA') {
            if (formData.get('setor_origem_id')) 
                payload.setor_origem_id = parseInt(formData.get('setor_origem_id'));
            if (formData.get('local_origem_id')) 
                payload.local_origem_id = parseInt(formData.get('local_origem_id'));
            if (formData.get('setor_destino_id')) 
                payload.setor_destino_id = parseInt(formData.get('setor_destino_id'));
            if (formData.get('local_destino_id')) 
                payload.local_destino_id = parseInt(formData.get('local_destino_id'));
        }
    }
    
    try {
        const res = await fetch('/lotes/iniciar', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.erro || 'Erro ao criar lote');
        }
        
        const data = await res.json();
        state.loteId = data.id_lote;
        
        // Atualizar display
        document.getElementById('display-lote-id').textContent = `#${state.loteId}`;
        
        // Ocultar form, mostrar seção de busca e itens
        document.getElementById('form-cabecalho').parentElement.style.display = 'none';
        document.getElementById('secao-busca').classList.remove('hidden');
        document.getElementById('secao-itens').classList.remove('hidden');
        
        // Focar no campo de busca
        document.getElementById('busca-produto').focus();
        
    } catch (error) {
        console.error('Erro ao iniciar lote:', error);
        alert(error.message);
    } finally {
        ocultarLoader();
    }
}

// ========================================
// BUSCA DE PRODUTO
// ========================================

async function buscarProduto() {
    const termo = document.getElementById('busca-produto').value.trim();
    const resultadosDiv = document.getElementById('resultados-busca');
    const btnLimpar = document.getElementById('btn-limpar-busca');
    
    if (termo.length < 2) {
        resultadosDiv.classList.add('hidden');
        btnLimpar.classList.add('hidden');
        return;
    }
    
    btnLimpar.classList.remove('hidden');
    
    try {
        const res = await fetch(`/api/produtos/buscar?q=${encodeURIComponent(termo)}`);
        const produtos = await res.json();
        
        if (produtos.length === 0) {
            resultadosDiv.innerHTML = '<div class="p-4 text-gray-400">Nenhum produto encontrado</div>';
            resultadosDiv.classList.remove('hidden');
            return;
        }
        
        let html = '';
        produtos.forEach(prod => {
            html += `
                <div class="p-3 hover:bg-slate-600 cursor-pointer border-b border-slate-600 last:border-0"
                     onclick="selecionarProduto(${JSON.stringify(prod).replace(/"/g, '&quot;')})">
                    <div class="font-semibold text-white">${prod.nome}</div>
                    <div class="text-xs text-gray-400">
                        ERP: ${prod.id_erp || '-'} | GTIN: ${prod.gtin || '-'} | 
                        Estoque: ${prod.estoque_atual} ${prod.unidade_simbolo}
                    </div>
                </div>
            `;
        });
        
        resultadosDiv.innerHTML = html;
        resultadosDiv.classList.remove('hidden');
        
    } catch (error) {
        console.error('Erro ao buscar produtos:', error);
    }
}

function limparBusca() {
    document.getElementById('busca-produto').value = '';
    document.getElementById('resultados-busca').classList.add('hidden');
    document.getElementById('btn-limpar-busca').classList.add('hidden');
    document.getElementById('busca-produto').focus();
}

async function selecionarProduto(produto) {
    state.produtoSelecionado = produto;
    
    // Ocultar resultados e limpar busca
    document.getElementById('resultados-busca').classList.add('hidden');
    limparBusca();
    
    // Buscar unidades disponíveis (Ajuste 4)
    try {
        const res = await fetch(`/api/produto/${produto.id}/unidades`);
        const unidades = await res.json();
        
        // Preencher modal
        document.getElementById('modal-produto-id').value = produto.id;
        document.getElementById('modal-produto-nome').textContent = produto.nome;
        document.getElementById('modal-produto-erp').textContent = produto.id_erp || '-';
        document.getElementById('modal-produto-gtin').textContent = produto.gtin || '-';
        document.getElementById('modal-produto-estoque').textContent = `${produto.estoque_atual} ${produto.unidade_simbolo}`;
        
        // Preencher select de unidades
        const selectUnidade = document.getElementById('modal-unidade');
        selectUnidade.innerHTML = '';
        
        // Unidade padrão
        const optPadrao = document.createElement('option');
        optPadrao.value = JSON.stringify({
            id: unidades.unidade_padrao.id,
            sigla: unidades.unidade_padrao.sigla,
            fator: 1.0
        });
        optPadrao.textContent = `${unidades.unidade_padrao.sigla} (padrão)`;
        optPadrao.selected = true;
        selectUnidade.appendChild(optPadrao);
        
        // Unidades alternativas
        unidades.unidades_alternativas.forEach(un => {
            const opt = document.createElement('option');
            opt.value = JSON.stringify({
                id: un.id,
                sigla: un.sigla,
                fator: un.fator
            });
            opt.textContent = `${un.sigla} (${un.fator}x)`;
            selectUnidade.appendChild(opt);
        });
        
        // Preencher preço de custo se ENTRADA (Ajuste 2)
        const campoPrecoCusto = document.getElementById('campo-preco-custo');
        if (state.tipo === 'ENTRADA') {
            document.getElementById('modal-preco-custo').value = produto.preco_custo.toFixed(2);
            campoPrecoCusto.classList.remove('hidden');
        } else {
            campoPrecoCusto.classList.add('hidden');
        }
        
        // Limpar quantidade e conversão
        document.getElementById('modal-quantidade').value = '';
        document.getElementById('conversao-unidade').textContent = '';
        
        // Adicionar listeners para atualização em tempo real
        document.getElementById('modal-quantidade').removeEventListener('input', atualizarConversao);
        document.getElementById('modal-unidade').removeEventListener('change', atualizarConversao);
        document.getElementById('modal-quantidade').addEventListener('input', atualizarConversao);
        document.getElementById('modal-unidade').addEventListener('change', atualizarConversao);
        
        // Remover foco do campo de busca (evita teclado virtual do celular)
        document.getElementById('busca-produto').blur();
        
        // Abrir modal
        document.getElementById('modal-adicionar-item').classList.remove('hidden');
        
    } catch (error) {
        console.error('Erro ao buscar unidades:', error);
        alert('Erro ao carregar unidades do produto');
    }
}

// ========================================
// MODAL E TECLADO NUMÉRICO (Ajuste 2)
// ========================================

function fecharModal() {
    document.getElementById('modal-adicionar-item').classList.add('hidden');
    
    // Retornar foco para campo de busca após pequeno delay
    setTimeout(() => {
        document.getElementById('busca-produto').focus();
    }, 100);
}

function digitarNumero(digito) {
    const input = document.getElementById('modal-quantidade');
    const valorAtual = input.value;
    
    // Evitar múltiplos pontos decimais
    if (digito === '.' && valorAtual.includes('.')) {
        return;
    }
    
    input.value = valorAtual + digito;
    atualizarConversao(); // Atualizar conversão em tempo real
}

function apagarDigito() {
    const input = document.getElementById('modal-quantidade');
    input.value = input.value.slice(0, -1);
    atualizarConversao(); // Atualizar conversão em tempo real
}

function limparQuantidade() {
    document.getElementById('modal-quantidade').value = '';
    document.getElementById('conversao-unidade').textContent = '';
}

function atualizarConversao() {
    const quantidadeInput = document.getElementById('modal-quantidade');
    const unidadeSelect = document.getElementById('modal-unidade');
    const conversaoDiv = document.getElementById('conversao-unidade');
    
    const quantidade = parseFloat(quantidadeInput.value);
    
    if (!quantidade || quantidade <= 0 || !unidadeSelect.value) {
        conversaoDiv.textContent = '';
        return;
    }
    
    const unidadeData = JSON.parse(unidadeSelect.value);
    const quantidadePadrao = quantidade * unidadeData.fator;
    
    // Obter sigla da unidade padrão do produto selecionado
    const unidadePadrao = state.produtoSelecionado.unidade_simbolo;
    
    // Mostrar conversão se não for unidade padrão
    if (unidadeData.fator !== 1.0) {
        conversaoDiv.innerHTML = `<span class="text-amber-400 font-bold">= ${quantidadePadrao.toFixed(2)} ${unidadePadrao}</span>`;
    } else {
        conversaoDiv.textContent = '';
    }
}

// ========================================
// ADICIONAR ITEM
// ========================================

async function adicionarItem(e) {
    e.preventDefault();
    
    const quantidade = parseFloat(document.getElementById('modal-quantidade').value);
    const unidadeJSON = document.getElementById('modal-unidade').value;
    const precoCusto = state.tipo === 'ENTRADA' ? 
        parseFloat(document.getElementById('modal-preco-custo').value) : null;
    
    if (!quantidade || quantidade <= 0) {
        alert('Quantidade inválida');
        return;
    }
    
    const unidadeData = JSON.parse(unidadeJSON);
    
    console.log('=== DEBUG: Adicionando Item ===');
    console.log('Lote ID:', state.loteId);
    console.log('Produto:', state.produtoSelecionado);
    console.log('Quantidade:', quantidade);
    console.log('Unidade:', unidadeData);
    
    mostrarLoader();
    
    const payload = {
        id_produto: state.produtoSelecionado.id,
        quantidade_original: quantidade,
        unidade_movimentacao: unidadeData.sigla,
        fator_conversao: unidadeData.fator
    };
    
    if (precoCusto !== null) {
        payload.preco_custo_unitario = precoCusto;
    }
    
    console.log('Payload:', payload);
    
    try {
        const url = `/lotes/${state.loteId}/item`;
        console.log('URL:', url);
        
        const res = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        console.log('Response status:', res.status);
        
        if (!res.ok) {
            const error = await res.json();
            console.error('Erro da API:', error);
            throw new Error(error.erro || 'Erro ao adicionar item');
        }
        
        const result = await res.json();
        console.log('Resultado:', result);
        
        // Recarregar lista de itens
        console.log('Recarregando itens...');
        await carregarItens();
        
        // Fechar modal
        fecharModal();
        
    } catch (error) {
        console.error('Erro ao adicionar item:', error);
        alert(error.message);
    } finally {
        ocultarLoader();
    }
}

async function carregarItens() {
    console.log('=== DEBUG: Carregando Itens ===');
    console.log('Lote ID:', state.loteId);
    
    try {
        const url = `/lotes/${state.loteId}`;
        console.log('URL:', url);
        
        const res = await fetch(url);
        console.log('Response status:', res.status);
        
        const data = await res.json();
        console.log('Dados recebidos:', data);
        
        state.itens = data.itens;
        console.log('Total de itens:', state.itens.length);
        
        const tbody = document.getElementById('tabela-itens');
        tbody.innerHTML = '';
        
        let total = 0;
        
        data.itens.forEach(item => {
            // Calcular quantidade na unidade padrão
            const quantidadePadrao = (item.quantidade_original || 0) * (item.fator_conversao || 1);
            const precoCusto = item.preco_custo_unitario || 0;
            const subtotal = quantidadePadrao * precoCusto;
            total += subtotal;
            
            // Formatar exibição da quantidade com conversão
            let displayQuantidade = `${item.quantidade_original} ${item.unidade_movimentacao}`;
            if (item.fator_conversao !== 1.0) {
                displayQuantidade += `<br><span class="text-xs text-amber-400">(${quantidadePadrao.toFixed(2)} ${item.unidade_padrao_sigla})</span>`;
            }
            
            const tr = document.createElement('tr');
            tr.className = 'border-b border-slate-700';
            tr.innerHTML = `
                <td class="py-2">${item.produto_nome}</td>
                <td class="text-right">${displayQuantidade}</td>
                <td class="text-right">R$ ${precoCusto.toFixed(2)}</td>
                <td class="text-right">R$ ${subtotal.toFixed(2)}</td>
                <td class="text-right">
                    <div class="flex justify-end gap-2">
                        <button onclick="abrirModalEditarItem(${item.id})" 
                                class="text-amber-400 hover:text-amber-300" title="Editar item">
                            ✏️
                        </button>
                        <button onclick="removerItem(${item.id})" 
                                class="text-red-400 hover:text-red-300" title="Remover item">
                            🗑️
                        </button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
        
        document.getElementById('valor-total').textContent = `R$ ${total.toFixed(2)}`;
        console.log('Itens carregados com sucesso! Total:', total);
        
    } catch (error) {
        console.error('Erro ao carregar itens:', error);
    }
}

async function removerItem(itemId) {
    if (!confirm('Remover este item?')) return;
    
    mostrarLoader();
    
    try {
        const res = await fetch(`/lotes/${state.loteId}/item/${itemId}`, {
            method: 'DELETE'
        });
        
        if (!res.ok) throw new Error('Erro ao remover item');
        
        await carregarItens();
        
    } catch (error) {
        console.error('Erro ao remover item:', error);
        alert('Erro ao remover item');
    } finally {
        ocultarLoader();
    }
}

// ========================================
// EDITAR ITEM
// ========================================

function abrirModalEditarItem(itemId) {
    const item = state.itens.find(i => i.id === itemId);
    if (!item) {
        alert('Item não encontrado');
        return;
    }
    document.getElementById('editar-item-id').value = item.id;
    document.getElementById('editar-produto-nome').textContent = item.produto_nome || '';
    document.getElementById('editar-quantidade').value = item.quantidade_original != null ? item.quantidade_original : '';
    document.getElementById('editar-preco').value = item.preco_custo_unitario != null ? item.preco_custo_unitario : '';
    document.getElementById('modal-editar-item').classList.remove('hidden');
}

function fecharModalEditarItem() {
    document.getElementById('modal-editar-item').classList.add('hidden');
    document.getElementById('editar-item-id').value = '';
    document.getElementById('editar-produto-nome').textContent = '';
    document.getElementById('editar-quantidade').value = '';
    document.getElementById('editar-preco').value = '';
}

async function salvarEdicaoItem(e) {
    e.preventDefault();
    const itemId = document.getElementById('editar-item-id').value;
    const quantidade = parseFloat(document.getElementById('editar-quantidade').value);
    const precoValor = document.getElementById('editar-preco').value;
    const preco = precoValor === '' ? null : parseFloat(precoValor);
    
    if (!quantidade || quantidade <= 0) {
        alert('Quantidade inválida');
        return;
    }
    
    const payload = { quantidade_original: quantidade };
    if (!Number.isNaN(preco) && preco !== null) {
        payload.preco_custo_unitario = preco;
    }
    
    mostrarLoader();
    
    try {
        const res = await fetch(`/lotes/${state.loteId}/item/${itemId}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.erro || 'Erro ao atualizar item');
        }
        
        await carregarItens();
        fecharModalEditarItem();
        
    } catch (error) {
        console.error('Erro ao editar item:', error);
        alert(error.message);
    } finally {
        ocultarLoader();
    }
}
// ========================================
// FINALIZAR LOTE
// ========================================

async function finalizarLote() {
    if (state.itens.length === 0) {
        alert('Adicione pelo menos um item antes de finalizar');
        return;
    }
    
    if (!confirm('Enviar lote para aprovação do gerente? Esta ação não pode ser desfeita.')) {
        return;
    }
    
    mostrarLoader();
    
    try {
        const res = await fetch(`/lotes/${state.loteId}/finalizar`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.erro || 'Erro ao finalizar lote');
        }
        
        const data = await res.json();
        
        alert(`✅ ${data.message}\n\nO gerente receberá o lote para análise e aprovação.`);
        window.location.href = '/';
        
    } catch (error) {
        console.error('Erro ao finalizar lote:', error);
        alert(error.message);
    } finally {
        ocultarLoader();
    }
}

// ========================================
// UTILIDADES
// ========================================

function mostrarLoader() {
    document.getElementById('loadingOverlay').classList.remove('hidden');
}

function ocultarLoader() {
    document.getElementById('loadingOverlay').classList.add('hidden');
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
