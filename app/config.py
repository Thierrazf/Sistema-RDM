import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent


def _valor_env(chave: str, default=""):
    if chave in os.environ:
        return os.environ[chave]

    for caminho in (Path.cwd() / ".env", BASE_DIR / ".env"):
        if caminho.exists():
            valor = dotenv_values(caminho).get(chave)
            if valor is not None:
                return valor
    return default


def _csv(valor: str) -> list[str]:
    return [p.strip() for p in (valor or "").replace(";", ",").split(",") if p.strip()]


class BaseConfig:
    # --- Sessão e CSRF ---------------------------------------------------
    SECRET_KEY = _valor_env("SECRET_KEY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_NAME = "rdm_session"
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.getenv("SESSION_LIFETIME_MIN", "30"))
    )
    WTF_CSRF_TIME_LIMIT = None  # expira junto com a sessão

    # --- Banco -----------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = _valor_env(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'rdm.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Identificação ---------------------------------------------------
    ORG_NOME = _valor_env("ORG_NOME", "Projeto piloto")

    # --- Regras de acesso ------------------------------------------------
    # Vazio = qualquer domínio. Em produção, restrinja aos domínios da organização.
    ALLOWED_EMAIL_DOMAINS = _csv(_valor_env("ALLOWED_EMAIL_DOMAINS", ""))
    MAX_TENTATIVAS_LOGIN = int(_valor_env("MAX_TENTATIVAS_LOGIN", "5"))
    BLOQUEIO_MINUTOS = int(_valor_env("BLOQUEIO_MINUTOS", "15"))
    SENHA_TAMANHO_MINIMO = 10

    # --- E-mail ----------------------------------------------------------
    SMTP_HOST = _valor_env("SMTP_HOST", "smtp.office365.com")
    SMTP_PORT = int(_valor_env("SMTP_PORT", "587"))
    SMTP_USER = _valor_env("SMTP_USER", "")
    SMTP_PASSWORD = _valor_env("SMTP_PASSWORD", "")
    EMAIL_REMETENTE = _valor_env("EMAIL_REMETENTE", "")
    EMAIL_NOME_REMETENTE = _valor_env("EMAIL_NOME_REMETENTE", "Gestao de Mudancas - TI")
    EMAIL_COPIA_PADRAO = _csv(_valor_env("EMAIL_COPIA_PADRAO", ""))

    # --- Microsoft Graph (alternativa ao SMTP) ---------------------------
    # "auto" usa a Graph quando as credenciais existem; aceita "graph" ou "smtp".
    EMAIL_BACKEND = _valor_env("EMAIL_BACKEND", "auto")
    GRAPH_TENANT_ID = _valor_env("GRAPH_TENANT_ID", "")
    GRAPH_CLIENT_ID = _valor_env("GRAPH_CLIENT_ID", "")
    GRAPH_CLIENT_SECRET = _valor_env("GRAPH_CLIENT_SECRET", "")

    # --- Arquivos --------------------------------------------------------
    PDF_DIR = BASE_DIR / "instance" / "pdfs"

    RATELIMIT_STORAGE_URI = _valor_env("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    # Gera uma chave aleatória para desenvolvimento se nenhuma foi definida em
    # ambiente/local; isso evita a configuração previsível e ainda permite rodar
    # em máquina local sem expor uma segredo padrão para todos os ambientes.
    SECRET_KEY = BaseConfig.SECRET_KEY or secrets.token_urlsafe(32)
    SESSION_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True     # exige HTTPS
    PREFERRED_URL_SCHEME = "https"

    def __init__(self):
        # Falha no boot em vez de rodar com chave previsível ou ausente.
        secret = os.environ.get("SECRET_KEY")
        if secret is None:
            secret = BaseConfig.SECRET_KEY or ""
        if not secret or len(secret) < 32:
            raise RuntimeError(
                "SECRET_KEY ausente ou fraca. Defina uma chave de no mínimo 32 "
                "caracteres na variável de ambiente SECRET_KEY antes de subir "
                "em produção."
            )
        self.SECRET_KEY = secret


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "teste"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    ALLOWED_EMAIL_DOMAINS = ["exemplo.com.br"]
    # O bloqueio por tentativas continua ativo; o limite por IP atrapalharia
    # os testes que fazem muitos logins seguidos.
    RATELIMIT_ENABLED = False


def get_config(nome: str | None = None):
    nome = (nome or os.getenv("FLASK_ENV") or "development").lower()
    if nome in ("production", "prod"):
        return ProductionConfig()
    if nome in ("testing", "test"):
        return TestingConfig
    return DevelopmentConfig
