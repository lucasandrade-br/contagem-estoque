import functools
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..db import get_db
from ..utils import get_local_ip

bp = Blueprint('auth', __name__)


def gerente_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if not session.get('is_gerente'):
            return redirect(url_for('auth.login_admin'))
        return view(**kwargs)
    return wrapped_view


@bp.route('/')
def index():
    db = get_db()
    
    # Buscar todos os usuários ativos (para contagem e movimentação)
    usuarios = db.execute(
        "SELECT * FROM usuarios WHERE ativo = 1 ORDER BY nome"
    ).fetchall()
    
    # Verificar se há inventário aberto (para mostrar seção de contagem)
    inventario_aberto = db.execute(
        "SELECT id FROM inventarios WHERE status = 'Aberto' LIMIT 1"
    ).fetchone() is not None
    
    local_ip = get_local_ip()
    
    return render_template(
        'auth/index.html', 
        usuarios=usuarios, 
        local_ip=local_ip,
        inventario_aberto=inventario_aberto
    )


@bp.route('/selecionar_usuario/<int:user_id>')
def selecionar_usuario(user_id):
    """Seleciona usuário para CONTAGEM (requer inventário aberto)."""
    db = get_db()
    cursor = db.execute("SELECT id FROM inventarios WHERE status = 'Aberto' LIMIT 1")
    if not cursor.fetchone():
        return render_template('erro_inventario.html'), 403

    usuario = db.execute('SELECT * FROM usuarios WHERE id = ? AND ativo = 1', (user_id,)).fetchone()
    if not usuario:
        return render_template('erro_inventario.html'), 403

    session['user_id'] = usuario['id']
    session['funcao'] = usuario['funcao']
    session['is_gerente'] = True if usuario['funcao'] == 'Gerente' else session.get('is_gerente', False)
    return redirect(url_for('estoque.setores'))


@bp.route('/selecionar_usuario_movimentacao/<int:user_id>')
def selecionar_usuario_movimentacao(user_id):
    """Seleciona usuário para MOVIMENTAÇÃO (não requer inventário aberto)."""
    db = get_db()
    
    usuario = db.execute('SELECT * FROM usuarios WHERE id = ? AND ativo = 1', (user_id,)).fetchone()
    if not usuario:
        flash('Usuário não encontrado', 'error')
        return redirect(url_for('auth.index'))
    
    # Salvar ID do usuário que está criando a movimentação
    session['user_movimentacao_id'] = usuario['id']
    session['user_movimentacao_nome'] = usuario['nome']
    
    return redirect(url_for('admin.lote_novo'))


@bp.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '').strip()

        db = get_db()
        gerente = db.execute(
            "SELECT * FROM usuarios WHERE funcao = 'Gerente' AND nome = ? AND senha = ?",
            (usuario, senha)
        ).fetchone()

        if gerente:
            session['user_id'] = gerente['id']
            session['is_gerente'] = True
            return redirect(url_for('admin.dashboard'))
        flash('Acesso negado.', 'error')

    return render_template('auth/login_admin.html')


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login_admin'))
