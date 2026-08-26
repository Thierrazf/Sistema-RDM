import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# O .env precisa ser carregado ANTES de qualquer os.getenv() deste módulo:
# as classes de configuração leem o ambiente já na definição, e um carregamento
# posterior chegaria tarde demais.
load_dotenv(BASE_DIR / ".env")   # raiz do projeto
load_dotenv(Path.cwd() / ".env")  # e o diretório de onde o comando foi executado


def _csv(valor: str) -> list[str]:
    return [p.strip() for p in (valor or "").replace(";", ",").split(",") if p.strip()]


class BaseConfig:
    # --- Sessão e CSRF ---------------------------------------------------
    SECRET_KEY = os.getenv("SECRET_KEY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_NAME = "rdm_session"
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.getenv("SESSION_LIFETIME_MIN", "30"))
    )
    WTF_CSRF_TIME_LIMIT = None  # expira junto com a sessão

    # --- Banco -----------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'rdm.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Regras de acesso ------------------------------------------------
    ALLOWED_EMAIL_DOMAINS = _csv(
        os.getenv("ALLOWED_EMAIL_DOMAINS", "exemplo.com.br,exemplo.com.br")
    )
    MAX_TENTATIVAS_LOGIN = int(os.getenv("MAX_TENTATIVAS_LOGIN", "5"))
    BLOQUEIO_MINUTOS = int(os.getenv("BLOQUEIO_MINUTOS", "15"))
    SENHA_TAMANHO_MINIMO = 10

    # --- E-mail ----------------------------------------------------------
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE", "")
    EMAIL_NOME_REMETENTE = os.getenv("EMAIL_NOME_REMETENTE", "Gestao de Mudancas - TI")
    EMAIL_COPIA_PADRAO = _csv(os.getenv("EMAIL_COPIA_PADRAO", ""))

    # --- Microsoft Graph (alternativa ao SMTP) ---------------------------
    # "auto" usa a Graph quando as credenciais existem; aceita "graph" ou "smtp".
    EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "auto")
    GRAPH_TENANT_ID = os.getenv("GRAPH_TENANT_ID", "")
    GRAPH_CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "")
    GRAPH_CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")

    # --- Arquivos --------------------------------------------------------
    PDF_DIR = BASE_DIR / "instance" / "pdfs"

    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = BaseConfig.SECRET_KEY or "dev-somente-local-nao-use-em-producao"
    SESSION_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True     # exige HTTPS
    PREFERRED_URL_SCHEME = "https"

    def __init__(self):
        # Falha no boot em vez de rodar com chave previsível.
        if not BaseConfig.SECRET_KEY or len(BaseConfig.SECRET_KEY) < 32:
            raise RuntimeError(
                "SECRET_KEY ausente ou fraca. Defina uma chave de no mínimo 32 "
                "caracteres na variável de ambiente SECRET_KEY antes de subir "
                "em produção."
            )


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "teste"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
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
