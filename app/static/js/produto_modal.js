// ============================================
// FUNÇÕES COMPARTILHADAS DO MODAL DE PRODUTO
// ============================================

/**
 * Toggle do estado disabled de um input de fator
 * @param {number} id - ID da unidade
 */
function toggleFator(id) {
    const chk = document.getElementById('chk_und_' + id);
    const input = document.getElementById('fator_' + id);
    if (chk && input) {
        input.disabled = !chk.checked;
        if (!chk.checked) input.value = '';
    }
}

/**
 * Abre o modal para um novo produto (limpa todos os campos)
 */
function abrirModalProduto() {
    document.getElementById('modalTitulo').innerText = 'Novo Produto';
    document.getElementById('prod_id').value = '';
    document.getElementById('prod_nome').value = '';
    document.getElementById('prod_iderp').value = '';
    document.getElementById('prod_gtin').value = '';
    document.getElementById('prod_categoria').value = '';
    document.getElementById('prod_unidade_padrao').value = '';
    
    const checkboxes = document.querySelectorAll('input[name="unidades_permitidas"]');
    checkboxes.forEach(cb => {
        cb.checked = false;
        toggleFator(cb.value);
    });

    document.getElementById('modalProduto').classList.remove('hidden');
}

/**
 * Abre o modal para editar um produto existente (busca dados via API)
 * @param {number} id - ID do produto a editar
 */
function editarProduto(id) {
    fetch(`/admin/produto/${id}`)
        .then(response => {
            if (!response.ok) throw new Error('Erro na requisição');
            return response.json();
        })
        .then(data => {
            // Campos Obrigatórios (Se esses falharem, tem erro grave no HTML)
            document.getElementById('modalTitulo').innerText = 'Editar Produto';
            document.getElementById('prod_id').value = data.id;
            document.getElementById('prod_nome').value = data.nome;

            // Campos Opcionais (Verifica se existem antes de preencher)
            // Isso previne o erro se você remover algum campo do HTML depois
            const elIdErp = document.getElementById('prod_iderp');
            if (elIdErp) elIdErp.value = data.id_erp || '';

            const elGtin = document.getElementById('prod_gtin');
            if (elGtin) elGtin.value = data.gtin || '';

            const elCategoria = document.getElementById('prod_categoria');
            if (elCategoria) elCategoria.value = data.categoria || '';

            // SEUS NOVOS CAMPOS
            const elCusto = document.getElementById('prod_preco_custo');
            if (elCusto) elCusto.value = data.preco_custo || '';

            const elVenda = document.getElementById('prod_preco_venda');
            if (elVenda) elVenda.value = data.preco_venda || '';

            // Unidade Padrão
            document.getElementById('prod_unidade_padrao').value = data.id_unidade_padrao;

            // Lógica das Unidades (Mantém igual, está correta)
            const checkboxes = document.querySelectorAll('input[name="unidades_permitidas"]');
            checkboxes.forEach(cb => {
                cb.checked = false;
                toggleFator(cb.value);
            });

            if (data.unidades_permitidas) {
                data.unidades_permitidas.forEach(u => {
                    const chk = document.getElementById('chk_und_' + u.id_unidade);
                    const input = document.getElementById('fator_' + u.id_unidade);
                    if (chk) {
                        chk.checked = true;
                        input.disabled = false;
                        input.value = u.fator_conversao;
                    }
                });
            }
            
            // Abre o modal
            document.getElementById('modalProduto').classList.remove('hidden');
        })
        .catch(err => {
            console.error('Erro detalhado:', err); // Ajuda a ver o erro real no F12
            alert('Erro ao carregar dados do produto. Verifique o console.');
        });
}

/**
 * Fecha o modal de produto
 */
function fecharModalProduto() {
    const modal = document.getElementById('modalProduto');
    if(modal) {
        modal.classList.add('hidden');
    }
}
