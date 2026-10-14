import re
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import CatalogoAtividade, ConfiguracaoIA, Equipe, LogAcesso, Perfil, User
from ..security import (
    admin_requerido,
    dominio_autorizado,
    email_valido,
    registrar_acesso,
    validar_senha,
)
from ..services.relatorio_ia_service import cifrar_api_key

admin_bp = Blueprint("admin", __name__)


def _enum(cls, valor):
    try:
        return cls[valor] if valor else None
    except KeyError:
        return None


# ------------------------------------------------------------------ usuários
@admin_bp.route("/usuarios")
@login_required
@admin_requerido
def usuarios():
    lista = db.session.query(User).order_by(User.ativo.desc(), User.nome).all()
    return render_template("admin/usuarios.html", usuarios=lista)


@admin_bp.route("/usuarios/novo", methods=["GET", "POST"])
@login_required
@admin_requerido
def usuario_novo():
    if request.method == "GET":
        return render_template("admin/usuario_form.html", u=None, modo="novo")

    nome = (request.form.get("nome") or "").strip()
    cargo = (request.form.get("cargo") or "").strip()
    telefone = (request.form.get("telefone") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    perfil = _enum(Perfil, request.form.get("perfil")) or Perfil.ANALISTA
    equipe = _enum(Equipe, request.form.get("equipe"))
    somente_referencia = request.form.get("somente_referencia") == "on"
    senha = request.form.get("senha") or ""

    erros = []
    if len(nome) < 3:
        erros.append("Informe o nome completo.")
    if not email_valido(email):
        erros.append("E-mail inválido.")
    elif not dominio_autorizado(email):
        erros.append("Use apenas e-mails dos domínios corporativos autorizados.")

    existente = db.session.query(User).filter_by(email=email).first()
    if existente:
        if not existente.ativo:
            existente.ativo = True
            existente.perfil = perfil
            existente.equipe = equipe
            existente.tentativas_falhas = 0
            existente.bloqueado_ate = None
            db.session.commit()
            flash(f"Usuário {existente.nome} reativado.", "success")
            return redirect(url_for("admin.usuarios"))
        erros.append("Já existe um usuário ativo com esse e-mail.")

    # Pessoa de referência não faz login, então não precisa de senha.
    if not somente_referencia:
        erros += ["A senha precisa " + item + "." for item in validar_senha(senha)]

    if erros:
        for e in erros:
            flash(e, "danger")
        return render_template("admin/usuario_form.html", u=None, modo="novo"), 400

    u = User(
        nome=nome,
        cargo=cargo or None,
        telefone=telefone or None,
        email=email,
        perfil=perfil,
        equipe=equipe,
        ativo=True,
        somente_referencia=somente_referencia,
        pode_enviar_email=request.form.get("pode_enviar_email") == "on",
    )
    u.definir_senha(senha or secrets.token_urlsafe(32))
    u.trocar_senha = not somente_referencia
    db.session.add(u)
    db.session.commit()
    registrar_acesso("USUARIO_CRIADO", email=email, usuario_id=current_user.id)

    if somente_referencia:
        flash(f"{nome} cadastrado como pessoa de referência (sem acesso ao sistema).", "success")
    else:
        flash(f"Usuário {nome} criado. A troca de senha será exigida no primeiro acesso.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@login_required
@admin_requerido
def usuario_editar(user_id):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)

    if request.method == "GET":
        return render_template("admin/usuario_form.html", u=u, modo="editar")

    nome = (request.form.get("nome") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    perfil = _enum(Perfil, request.form.get("perfil")) or u.perfil

    erros = []
    if len(nome) < 3:
        erros.append("Informe o nome completo.")
    if not email_valido(email) or not dominio_autorizado(email):
        erros.append("E-mail inválido ou fora dos domínios autorizados.")
    if db.session.query(User).filter(User.email == email, User.id != u.id).first():
        erros.append("Outro usuário já usa esse e-mail.")

    # Impede o administrador de remover o próprio acesso e travar o sistema.
    if u.id == current_user.id and perfil != Perfil.ADMIN:
        erros.append("Você não pode rebaixar o próprio perfil.")

    if erros:
        for e in erros:
            flash(e, "danger")
        return render_template("admin/usuario_form.html", u=u, modo="editar"), 400

    u.nome = nome
    u.cargo = (request.form.get("cargo") or "").strip() or None
    u.telefone = (request.form.get("telefone") or "").strip() or None
    u.email = email
    u.perfil = perfil
    u.equipe = _enum(Equipe, request.form.get("equipe"))
    if u.id != current_user.id:
        u.somente_referencia = request.form.get("somente_referencia") == "on"
    u.pode_enviar_email = request.form.get("pode_enviar_email") == "on"
    if u.id != current_user.id:
        u.ativo = request.form.get("ativo") == "on"

    db.session.commit()
    flash("Usuário atualizado.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/senha-temporaria", methods=["POST"])
@login_required
@admin_requerido
def usuario_senha_temporaria(user_id):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)

    temporaria = secrets.token_urlsafe(9) + "Aa1!"
    u.definir_senha(temporaria)
    u.trocar_senha = True
    u.tentativas_falhas = 0
    u.bloqueado_ate = None
    u.limpar_token_reset()
    db.session.commit()
    registrar_acesso("SENHA_TEMPORARIA", email=u.email, usuario_id=current_user.id)

    flash(
        f"Senha temporária de {u.nome}: {temporaria} — entregue pessoalmente. "
        "A troca será exigida no primeiro acesso.",
        "warning",
    )
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/desativar", methods=["POST"])
@login_required
@admin_requerido
def usuario_desativar(user_id):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)
    if u.id == current_user.id:
        flash("Você não pode desativar a própria conta.", "danger")
        return redirect(url_for("admin.usuarios"))

    u.ativo = False
    u.pode_enviar_email = False
    db.session.commit()
    registrar_acesso("USUARIO_DESATIVADO", email=u.email, usuario_id=current_user.id)
    flash(f"{u.nome} desativado.", "success")
    return redirect(url_for("admin.usuarios"))


# ------------------------------------------------------------------ catálogo
@admin_bp.route("/catalogo", methods=["GET", "POST"])
@login_required
@admin_requerido
def catalogo():
    if request.method == "POST":
        equipe = _enum(Equipe, request.form.get("equipe"))
        descricao = (request.form.get("descricao") or "").strip()
        duracao = request.form.get("duracao_min") or "0"
        if equipe and descricao:
            db.session.add(
                CatalogoAtividade(
                    equipe=equipe,
                    descricao=descricao,
                    duracao_min=int(duracao) if duracao.isdigit() else 0,
                    rollback=(request.form.get("rollback") or "").strip() or None,
                )
            )
            db.session.commit()
            flash("Atividade adicionada ao catálogo.", "success")
        else:
            flash("Escolha a equipe e descreva a atividade.", "danger")
        return redirect(url_for("admin.catalogo"))

    itens = (
        db.session.query(CatalogoAtividade)
        .order_by(CatalogoAtividade.equipe, CatalogoAtividade.descricao)
        .all()
    )
    return render_template("admin/catalogo.html", itens=itens, equipes=list(Equipe))


@admin_bp.route("/catalogo/<int:item_id>/remover", methods=["POST"])
@login_required
@admin_requerido
def catalogo_remover(item_id):
    item = db.session.get(CatalogoAtividade, item_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        flash("Item removido do catálogo.", "success")
    return redirect(url_for("admin.catalogo"))


# ----------------------------------------------------------------- auditoria
@admin_bp.route("/auditoria")
@login_required
@admin_requerido
def auditoria():
    pagina = request.args.get("pagina", 1, type=int)
    paginacao = db.paginate(
        db.session.query(LogAcesso).order_by(LogAcesso.criado_em.desc()),
        page=pagina,
        per_page=40,
        error_out=False,
    )
    return render_template("admin/auditoria.html", paginacao=paginacao)


# ----------------------------------------------------------- integração OpenAI
@admin_bp.route("/relatorios-ia", methods=["GET", "POST"])
@login_required
@admin_requerido
def configuracao_relatorios_ia():
    configuracao = db.session.get(ConfiguracaoIA, 1)
    if not configuracao:
        configuracao = ConfiguracaoIA(id=1, provedor="openai", modelo="gpt-4o-mini")

    if request.method == "POST":
        provedor = (request.form.get("provedor") or "").strip().lower()
        modelo = (request.form.get("modelo") or "").strip()
        url_compativel = (request.form.get("url_compativel") or "").strip()
        api_key = (request.form.get("api_key") or "").strip()
        erros = []
        provedores = {"openai", "anthropic", "gemini", "openai_compatible"}
        if provedor not in provedores:
            erros.append("Selecione um provedor de IA suportado.")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", modelo):
            erros.append("Informe um identificador de modelo válido.")
        if provedor == "openai_compatible":
            if (
                len(url_compativel) > 500
                or not re.fullmatch(r"https://[^/\s?#]+(?:/[^?#\s]*)?", url_compativel)
            ):
                erros.append("Informe uma URL base HTTPS válida para a API compatível.")
        else:
            url_compativel = ""
        if len(api_key) > 500:
            erros.append("A chave da API excede o tamanho permitido.")
        if (
            provedor != configuracao.provedor
            and request.form.get("remover_api_key") != "on"
            and not api_key
        ):
            erros.append("Informe a chave do novo provedor ao alterar a integração.")
        if request.form.get("remover_api_key") != "on" and not (
            configuracao.api_key_cifrada or api_key
        ):
            erros.append("Informe a chave do provedor selecionado para habilitar os relatórios.")

        if erros:
            for erro in erros:
                flash(erro, "danger")
            return render_template(
                "admin/relatorios_ia.html",
                configuracao=configuracao,
                chave_configurada=bool(configuracao.api_key_cifrada),
            ), 400

        configuracao.provedor = provedor
        configuracao.modelo = modelo
        configuracao.url_compativel = url_compativel or None
        if request.form.get("remover_api_key") == "on":
            configuracao.api_key_cifrada = None
        elif api_key:
            configuracao.api_key_cifrada = cifrar_api_key(api_key)
        db.session.add(configuracao)
        db.session.commit()
        registrar_acesso(
            "CONFIGURACAO_IA",
            usuario_id=current_user.id,
            detalhe="Configuração da integração de relatórios atualizada.",
        )
        flash("Configuração dos relatórios por IA atualizada.", "success")
        return redirect(url_for("admin.configuracao_relatorios_ia"))

    return render_template(
        "admin/relatorios_ia.html",
        configuracao=configuracao,
        chave_configurada=bool(configuracao.api_key_cifrada),
    )
