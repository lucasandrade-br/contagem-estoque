"""
Script para Limpeza de Dados de Teste
======================================

Este script remove TODAS as movimentações e operações de teste,
mantendo intactos os dados cadastrais (produtos, usuários, etc).

ATENÇÃO: Esta ação é IRREVERSÍVEL após a execução!
Um backup será criado automaticamente antes da limpeza.

Uso:
    python tools/limpar_dados_teste.py

Autor: Sistema de Estoque
Data: Janeiro 2026
"""

import os
import sys
import sqlite3
import shutil
from datetime import datetime

# Configurações
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'database.db')
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')

# Tabelas que serão LIMPAS (dados operacionais)
TABELAS_LIMPAR = [
    'contagens',
    'estoque_saldos',
    'historico_status_locais',
    'inventarios',
    'logs_auditoria',
    'lotes_movimentacao',
    'lotes_movimentacao_itens',
    'movimentacoes',
    'ocorrencias'
]


def criar_backup():
    """
    Cria backup do banco de dados antes de limpar.
    """
    print("\n" + "="*70)
    print("📦 CRIANDO BACKUP DE SEGURANÇA")
    print("="*70)
    
    if not os.path.exists(DB_PATH):
        print(f"❌ ERRO: Banco de dados não encontrado!")
        print(f"   Caminho: {DB_PATH}")
        return False
    
    # Cria pasta de backups se não existir
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    # Nome do backup com timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BACKUP_DIR, f'antes_limpar_{timestamp}.db')
    
    try:
        print(f"\n📋 Copiando: {DB_PATH}")
        print(f"📂 Destino:  {backup_file}")
        
        shutil.copy2(DB_PATH, backup_file)
        
        tamanho_mb = os.path.getsize(backup_file) / (1024 * 1024)
        print(f"\n✅ Backup criado com sucesso!")
        print(f"   Tamanho: {tamanho_mb:.2f} MB")
        print(f"   Arquivo: {os.path.basename(backup_file)}")
        print("="*70)
        
        return backup_file
        
    except Exception as e:
        print(f"\n❌ ERRO ao criar backup: {e}")
        print("="*70)
        return False


def contar_registros(conn):
    """
    Conta quantos registros existem em cada tabela antes de limpar.
    """
    print("\n" + "="*70)
    print("📊 CONTAGEM DE REGISTROS (ANTES DA LIMPEZA)")
    print("="*70)
    
    totais = {}
    total_geral = 0
    
    for tabela in TABELAS_LIMPAR:
        try:
            cursor = conn.execute(f'SELECT COUNT(*) FROM {tabela}')
            count = cursor.fetchone()[0]
            totais[tabela] = count
            total_geral += count
            
            # Formatação com ícone
            icone = "📦" if count > 0 else "⚪"
            print(f"   {icone} {tabela:30s} → {count:6d} registros")
            
        except sqlite3.Error as e:
            print(f"   ⚠️  {tabela:30s} → Erro: {e}")
            totais[tabela] = 0
    
    print("-"*70)
    print(f"   🔢 TOTAL GERAL: {total_geral:,} registros serão removidos")
    print("="*70)
    
    return totais, total_geral


def limpar_tabelas(conn):
    """
    Remove todos os registros das tabelas operacionais.
    """
    print("\n" + "="*70)
    print("🗑️  LIMPANDO DADOS DE TESTE")
    print("="*70)
    
    registros_removidos = {}
    
    # Desabilita foreign keys temporariamente para evitar erros
    conn.execute('PRAGMA foreign_keys = OFF')
    
    for tabela in TABELAS_LIMPAR:
        try:
            print(f"\n🔄 Limpando tabela: {tabela}...")
            
            # Conta antes de deletar
            cursor = conn.execute(f'SELECT COUNT(*) FROM {tabela}')
            count_antes = cursor.fetchone()[0]
            
            # Remove todos os registros
            conn.execute(f'DELETE FROM {tabela}')
            
            # Reseta o auto-increment (ID volta para 1)
            conn.execute(f"DELETE FROM sqlite_sequence WHERE name='{tabela}'")
            
            # Confirma remoção
            cursor = conn.execute(f'SELECT COUNT(*) FROM {tabela}')
            count_depois = cursor.fetchone()[0]
            
            registros_removidos[tabela] = count_antes
            
            if count_depois == 0 and count_antes > 0:
                print(f"   ✅ {count_antes} registros removidos")
            elif count_antes == 0:
                print(f"   ⚪ Tabela já estava vazia")
            else:
                print(f"   ⚠️  Ainda restam {count_depois} registros")
                
        except sqlite3.Error as e:
            print(f"   ❌ ERRO: {e}")
            registros_removidos[tabela] = 0
    
    # Reabilita foreign keys
    conn.execute('PRAGMA foreign_keys = ON')
    
    # Commit das alterações
    conn.commit()
    
    print("\n" + "="*70)
    print("✅ LIMPEZA CONCLUÍDA!")
    print("="*70)
    
    return registros_removidos


def verificar_limpeza(conn):
    """
    Verifica se todas as tabelas foram realmente limpas.
    """
    print("\n" + "="*70)
    print("🔍 VERIFICAÇÃO PÓS-LIMPEZA")
    print("="*70)
    
    tudo_limpo = True
    
    for tabela in TABELAS_LIMPAR:
        try:
            cursor = conn.execute(f'SELECT COUNT(*) FROM {tabela}')
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"   ✅ {tabela:30s} → 0 registros (OK)")
            else:
                print(f"   ⚠️  {tabela:30s} → {count} registros (ATENÇÃO!)")
                tudo_limpo = False
                
        except sqlite3.Error as e:
            print(f"   ❌ {tabela:30s} → Erro: {e}")
            tudo_limpo = False
    
    print("="*70)
    
    if tudo_limpo:
        print("\n🎉 SUCESSO! Todas as tabelas operacionais foram limpas.")
        print("   Os dados cadastrais (produtos, usuários, etc) foram preservados.\n")
    else:
        print("\n⚠️  ATENÇÃO! Algumas tabelas ainda têm registros.")
        print("   Verifique os erros acima.\n")
    
    return tudo_limpo


def mostrar_dados_preservados(conn):
    """
    Mostra quais dados cadastrais foram preservados.
    """
    print("="*70)
    print("💾 DADOS PRESERVADOS (Cadastros)")
    print("="*70)
    
    tabelas_preservadas = [
        ('usuarios', 'Usuários'),
        ('produtos', 'Produtos'),
        ('categorias', 'Categorias'),
        ('locais', 'Locais'),
        ('setores', 'Setores'),
        ('unidades_medida', 'Unidades de Medida'),
        ('configs', 'Configurações')
    ]
    
    for tabela, nome in tabelas_preservadas:
        try:
            cursor = conn.execute(f'SELECT COUNT(*) FROM {tabela}')
            count = cursor.fetchone()[0]
            print(f"   ✅ {nome:25s} → {count:4d} registros mantidos")
        except sqlite3.Error:
            pass
    
    print("="*70 + "\n")


def main():
    """
    Função principal do script.
    """
    print("\n" + "="*70)
    print("🧹 SCRIPT DE LIMPEZA DE DADOS DE TESTE")
    print("="*70)
    print("\nEste script irá remover TODAS as movimentações e operações,")
    print("mantendo apenas os dados cadastrais (produtos, usuários, etc).\n")
    print("⚠️  ATENÇÃO: Esta ação é IRREVERSÍVEL!")
    print("⚠️  Um backup será criado antes da limpeza.\n")
    
    # Verificar se banco existe
    if not os.path.exists(DB_PATH):
        print(f"❌ ERRO: Banco de dados não encontrado!")
        print(f"   Caminho esperado: {DB_PATH}\n")
        return
    
    # Listar tabelas que serão limpas
    print("📋 TABELAS QUE SERÃO LIMPAS:")
    for i, tabela in enumerate(TABELAS_LIMPAR, 1):
        print(f"   {i}. {tabela}")
    
    print("\n" + "-"*70)
    
    # Primeira confirmação
    print("\n⚠️  CONFIRMAÇÃO 1/2")
    resposta1 = input("Digite 'SIM' para continuar ou 'N' para cancelar: ").strip().upper()
    
    if resposta1 != 'SIM':
        print("\n❌ Operação cancelada pelo usuário.\n")
        return
    
    # Segunda confirmação (mais rigorosa)
    print("\n⚠️  CONFIRMAÇÃO 2/2 (ÚLTIMA CHANCE!)")
    print("Digite exatamente 'LIMPAR TUDO' para confirmar:")
    resposta2 = input("> ").strip()
    
    if resposta2 != 'LIMPAR TUDO':
        print("\n❌ Operação cancelada. Texto de confirmação incorreto.\n")
        return
    
    print("\n✅ Confirmações recebidas. Iniciando processo...\n")
    
    # Criar backup
    backup_file = criar_backup()
    if not backup_file:
        print("\n❌ ABORTADO! Não foi possível criar backup.\n")
        return
    
    # Conectar ao banco
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        # Contar registros antes
        totais_antes, total_geral = contar_registros(conn)
        
        if total_geral == 0:
            print("\n✅ Banco já está limpo! Nenhum registro para remover.\n")
            conn.close()
            return
        
        # Última pausa antes de executar
        print("\n⏸️  Última chance para interromper!")
        print("   Pressione Ctrl+C para cancelar ou Enter para continuar...")
        try:
            input()
        except KeyboardInterrupt:
            print("\n\n❌ Operação cancelada pelo usuário.\n")
            conn.close()
            return
        
        # Executar limpeza
        registros_removidos = limpar_tabelas(conn)
        
        # Verificar resultado
        sucesso = verificar_limpeza(conn)
        
        # Mostrar dados preservados
        mostrar_dados_preservados(conn)
        
        # Fechar conexão
        conn.close()
        
        # Resumo final
        print("="*70)
        print("📊 RESUMO DA OPERAÇÃO")
        print("="*70)
        print(f"   ✅ Backup criado: {os.path.basename(backup_file)}")
        print(f"   🗑️  Registros removidos: {sum(registros_removidos.values()):,}")
        print(f"   💾 Dados cadastrais preservados")
        
        if sucesso:
            print(f"   🎉 Status: SUCESSO")
        else:
            print(f"   ⚠️  Status: CONCLUÍDO COM AVISOS")
        
        print("="*70)
        print("\n✨ Sistema pronto para uso em produção!\n")
        
    except sqlite3.Error as e:
        print(f"\n❌ ERRO de banco de dados: {e}\n")
        return
    except KeyboardInterrupt:
        print("\n\n❌ Operação interrompida pelo usuário.\n")
        return
    except Exception as e:
        print(f"\n❌ ERRO inesperado: {e}\n")
        return


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Script interrompido.\n")
        sys.exit(1)
