import re
from functools import wraps

from flask import abort, current_app, request
from flask_login import current_user

from .extensions import db
from .models import LogAcesso

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


# ---------------------------------------------------------------- decorators
def perfil_requerido(*perfis):
    """Restringe a rota a determinados perfis. Use sempre junto de @login_required."""

    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.perfil not in perfis:
                abort(403)
            return f(*args, **kwargs)

        return decorated

    return wrapper


def admin_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated


def gestor_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.is_gestor:
            abort(403)
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------- validações
def email_valido(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))


def dominio_autorizado(email: str) -> bool:
    dominios = current_app.config.get("ALLOWED_EMAIL_DOMAINS") or []
    if not dominios:
        return True
    dominio = (email or "").strip().lower().rsplit("@", 1)[-1]
    return dominio in [d.lower() for d in dominios]


def validar_senha(senha: str) -> list[str]:
    """Retorna a lista de exigências não atendidas. Lista vazia = senha aceita."""
    minimo = current_app.config.get("SENHA_TAMANHO_MINIMO", 10)
    erros = []
    senha = senha or ""
    if len(senha) < minimo:
        erros.append(f"ter no mínimo {minimo} caracteres")
    if not re.search(r"[a-z]", senha):
        erros.append("conter letra minúscula")
    if not re.search(r"[A-Z]", senha):
        erros.append("conter letra maiúscula")
    if not re.search(r"\d", senha):
        erros.append("conter número")
    if not re.search(r"[^\w\s]", senha):
        erros.append("conter caractere especial")
    return erros


def normalizar_emails(*valores) -> list[str]:
    """Aceita strings com vírgula/ponto e vírgula e devolve lista única e válida."""
    saida, vistos = [], set()
    for valor in valores:
        if not valor:
            continue
        if isinstance(valor, (list, tuple, set)):
            partes = list(valor)
        else:
            partes = str(valor).replace(";", ",").split(",")
        for p in partes:
            p = str(p).strip()
            if not p or not email_valido(p):
                continue
            chave = p.lower()
            if chave not in vistos:
                vistos.add(chave)
                saida.append(p)
    return saida


# ---------------------------------------------------------------- auditoria
def registrar_acesso(evento: str, email: str = "", usuario_id=None, detalhe: str = ""):
    db.session.add(
        LogAcesso(
            email=(email or "")[:180],
            usuario_id=usuario_id,
            evento=evento,
            ip=(request.headers.get("X-Forwarded-For", request.remote_addr) or "")[:64],
            user_agent=(request.user_agent.string or "")[:255],
            detalhe=detalhe[:255],
        )
    )
    db.session.commit()


# ---------------------------------------------------------------- cabeçalhos
def aplicar_cabecalhos_seguranca(resposta):
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    resposta.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if not current_app.debug:
        resposta.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return resposta
