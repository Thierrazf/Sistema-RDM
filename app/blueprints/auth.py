from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db, limiter
from ..models import User
from ..security import (
    dominio_autorizado,
    email_valido,
    registrar_acesso,
    validar_senha,
)
from ..services.email_service import enviar

auth_bp = Blueprint("auth", __name__)

MSG_GENERICA = "E-mail ou senha inválidos."


def _destino_seguro(destino: str | None) -> str:
    """Evita open redirect: só aceita caminho relativo do próprio site."""
    if not destino:
        return url_for("painel.inicio")
    parsed = urlparse(destino)
    if parsed.netloc or parsed.scheme:
        return url_for("painel.inicio")
    return destino


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 40 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("painel.inicio"))

    if request.method == "GET":
        return render_template("auth/login.html")

    email = (request.form.get("email") or "").strip().lower()
    senha = request.form.get("senha") or ""

    user = db.session.query(User).filter_by(email=email).first()

    # Resposta idêntica para usuário inexistente e senha errada.
    if not user:
        registrar_acesso("LOGIN_FALHA", email=email, detalhe="usuário inexistente")
        flash(MSG_GENERICA, "danger")
        return render_template("auth/login.html", email=email), 401

    if user.bloqueado:
        registrar_acesso("LOGIN_BLOQUEADO", email=email, usuario_id=user.id)
        flash(
            "Conta temporariamente bloqueada por excesso de tentativas. "
            f"Tente novamente em {current_app.config['BLOQUEIO_MINUTOS']} minutos.",
            "danger",
        )
        return render_template("auth/login.html", email=email), 401

    if not user.conferir_senha(senha):
        user.registrar_falha(
            current_app.config["MAX_TENTATIVAS_LOGIN"],
            current_app.config["BLOQUEIO_MINUTOS"],
        )
        db.session.commit()
        registrar_acesso("LOGIN_FALHA", email=email, usuario_id=user.id, detalhe="senha")
        flash(MSG_GENERICA, "danger")
        return render_template("auth/login.html", email=email), 401

    if not user.pode_entrar:
        registrar_acesso("LOGIN_INATIVO", email=email, usuario_id=user.id)
        flash("Conta sem acesso ao sistema. Procure o administrador.", "danger")
        return render_template("auth/login.html", email=email), 401

    # Regra de domínio vale para todos os perfis, inclusive administrador.
    if not dominio_autorizado(email):
        registrar_acesso("LOGIN_DOMINIO", email=email, usuario_id=user.id)
        flash("Acesso permitido apenas para e-mails corporativos.", "danger")
        return render_template("auth/login.html", email=email), 403

    user.registrar_sucesso()
    db.session.commit()

    login_user(user, remember=False)
    registrar_acesso("LOGIN_OK", email=email, usuario_id=user.id)

    if user.trocar_senha:
        flash("Defina uma nova senha para continuar.", "info")
        return redirect(url_for("auth.alterar_senha"))

    return redirect(_destino_seguro(request.args.get("next")))


@auth_bp.route("/logout")
@login_required
def logout():
    registrar_acesso("LOGOUT", email=current_user.email, usuario_id=current_user.id)
    logout_user()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/alterar-senha", methods=["GET", "POST"])
@login_required
def alterar_senha():
    if request.method == "GET":
        return render_template("auth/alterar_senha.html")

    atual = request.form.get("senha_atual") or ""
    nova = request.form.get("senha") or ""
    confirma = request.form.get("senha_confirma") or ""

    if not current_user.conferir_senha(atual):
        flash("Senha atual incorreta.", "danger")
        return render_template("auth/alterar_senha.html"), 400

    if nova != confirma:
        flash("A confirmação não confere com a nova senha.", "danger")
        return render_template("auth/alterar_senha.html"), 400

    erros = validar_senha(nova)
    if erros:
        flash("A senha precisa " + ", ".join(erros) + ".", "danger")
        return render_template("auth/alterar_senha.html"), 400

    current_user.definir_senha(nova)
    db.session.commit()
    registrar_acesso("SENHA_ALTERADA", email=current_user.email, usuario_id=current_user.id)
    flash("Senha alterada.", "success")
    return redirect(url_for("painel.inicio"))


@auth_bp.route("/esqueci-senha", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def esqueci_senha():
    if request.method == "GET":
        return render_template("auth/esqueci_senha.html")

    email = (request.form.get("email") or "").strip().lower()
    # Resposta sempre igual — não revela se o e-mail existe na base.
    resposta = redirect(url_for("auth.login"))
    flash(
        "Se o e-mail estiver cadastrado, você receberá as instruções em instantes.",
        "info",
    )

    if not email_valido(email) or not dominio_autorizado(email):
        return resposta

    user = db.session.query(User).filter_by(email=email, ativo=True).first()
    if not user:
        return resposta

    token = user.gerar_token_reset(validade_min=30)
    db.session.commit()
    registrar_acesso("RESET_SOLICITADO", email=email, usuario_id=user.id)

    link = url_for("auth.redefinir_senha", token=token, _external=True)
    html = render_template("email/reset.html", user=user, link=link)
    texto = render_template("email/reset.txt", user=user, link=link)
    try:
        enviar([user.email], "Redefinição de senha — Gestão de Mudanças", html, texto)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("Falha ao enviar reset: %s", exc)

    return resposta


@auth_bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def redefinir_senha(token):
    user = (
        db.session.query(User)
        .filter_by(reset_token_hash=User._hash_token(token))
        .first()
    )
    if not user or not user.token_reset_valido(token):
        flash("Link inválido ou expirado. Solicite um novo.", "danger")
        return redirect(url_for("auth.esqueci_senha"))

    if request.method == "GET":
        return render_template("auth/redefinir_senha.html", token=token)

    nova = request.form.get("senha") or ""
    confirma = request.form.get("senha_confirma") or ""

    if nova != confirma:
        flash("A confirmação não confere com a nova senha.", "danger")
        return render_template("auth/redefinir_senha.html", token=token), 400

    erros = validar_senha(nova)
    if erros:
        flash("A senha precisa " + ", ".join(erros) + ".", "danger")
        return render_template("auth/redefinir_senha.html", token=token), 400

    user.definir_senha(nova)
    user.limpar_token_reset()
    user.tentativas_falhas = 0
    user.bloqueado_ate = None
    db.session.commit()
    registrar_acesso("RESET_CONCLUIDO", email=user.email, usuario_id=user.id)

    flash("Senha redefinida. Faça login com a nova senha.", "success")
    return redirect(url_for("auth.login"))
