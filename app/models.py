import enum
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from sqlalchemy import Enum as SAEnum
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def agora() -> datetime:
    return datetime.now(timezone.utc)


# =====================================================================
# Enums
# =====================================================================
class Equipe(str, enum.Enum):
    INFRAESTRUTURA = "Infraestrutura"
    FRONTEND = "Desenvolvimento Front-end"
    BACKEND = "Desenvolvimento Back-end"
    BANCO_DADOS = "Banco de Dados"

    @property
    def slug(self) -> str:
        return self.name.lower().replace("_", "-")


class Perfil(str, enum.Enum):
    ADMIN = "Administrador"
    GESTOR = "Gestor"
    ANALISTA = "Analista"


class StatusRDM(str, enum.Enum):
    RASCUNHO = "Rascunho"
    ABERTA = "Aberta"
    EM_ANALISE = "Em análise"
    APROVADA = "Aprovada"
    EXECUTADA = "Executada"
    CANCELADA = "Cancelada"
    FECHADA = "Fechada"


class StatusAtividade(str, enum.Enum):
    PENDENTE = "Pendente"
    EXECUTADA = "Executada"
    FALHOU = "Falhou"
    NAO_APLICADA = "Não aplicada"


class ResultadoRDM(str, enum.Enum):
    SUCESSO = "Concluída com sucesso"
    SUCESSO_RESSALVA = "Concluída com ressalvas"
    ROLLBACK = "Revertida por rollback"
    NAO_EXECUTADA = "Não executada"

    @property
    def slug(self) -> str:
        return self.name.lower().replace("_", "-")


class Criticidade(str, enum.Enum):
    BAIXA = "Baixa"
    MEDIA = "Média"
    ALTA = "Alta"
    CRITICA = "Crítica"


# =====================================================================
# Usuário
# =====================================================================
class User(UserMixin, db.Model):
    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    cargo = db.Column(db.String(120))  # patente ou cargo: "2º Ten", "Ten Cel", "Analista"
    telefone = db.Column(db.String(40))
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(255), nullable=False)

    perfil = db.Column(SAEnum(Perfil), default=Perfil.ANALISTA, nullable=False)
    equipe = db.Column(SAEnum(Equipe), nullable=True)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    pode_enviar_email = db.Column(db.Boolean, default=False, nullable=False)
    # Pessoa que aparece nos seletores da RDM mas não acessa o sistema.
    somente_referencia = db.Column(db.Boolean, default=False, nullable=False)

    trocar_senha = db.Column(db.Boolean, default=True, nullable=False)
    senha_alterada_em = db.Column(db.DateTime(timezone=True))

    tentativas_falhas = db.Column(db.Integer, default=0, nullable=False)
    bloqueado_ate = db.Column(db.DateTime(timezone=True))
    ultimo_acesso = db.Column(db.DateTime(timezone=True))

    # Token de reset guardado como hash — vazamento do banco não permite reset.
    reset_token_hash = db.Column(db.String(64), index=True)
    reset_token_expira = db.Column(db.DateTime(timezone=True))

    criado_em = db.Column(db.DateTime(timezone=True), default=agora, nullable=False)

    # ---------------- senha ----------------
    def definir_senha(self, senha: str) -> None:
        self.senha_hash = generate_password_hash(senha, method="scrypt")
        self.senha_alterada_em = agora()
        self.trocar_senha = False

    def conferir_senha(self, senha: str) -> bool:
        return check_password_hash(self.senha_hash, senha or "")

    # ---------------- bloqueio ----------------
    @property
    def bloqueado(self) -> bool:
        if not self.bloqueado_ate:
            return False
        return agora() < self.bloqueado_ate.replace(tzinfo=timezone.utc)

    def registrar_falha(self, maximo: int, minutos: int) -> None:
        self.tentativas_falhas = (self.tentativas_falhas or 0) + 1
        if self.tentativas_falhas >= maximo:
            self.bloqueado_ate = agora() + timedelta(minutes=minutos)

    def registrar_sucesso(self) -> None:
        self.tentativas_falhas = 0
        self.bloqueado_ate = None
        self.ultimo_acesso = agora()

    # ---------------- reset ----------------
    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def gerar_token_reset(self, validade_min: int = 30) -> str:
        token = secrets.token_urlsafe(48)
        self.reset_token_hash = self._hash_token(token)
        self.reset_token_expira = agora() + timedelta(minutes=validade_min)
        return token

    def token_reset_valido(self, token: str) -> bool:
        if not self.reset_token_hash or not self.reset_token_expira:
            return False
        if agora() > self.reset_token_expira.replace(tzinfo=timezone.utc):
            return False
        return secrets.compare_digest(self.reset_token_hash, self._hash_token(token))

    def limpar_token_reset(self) -> None:
        self.reset_token_hash = None
        self.reset_token_expira = None

    # ---------------- permissões ----------------
    @property
    def is_admin(self) -> bool:
        return self.perfil == Perfil.ADMIN

    @property
    def is_gestor(self) -> bool:
        return self.perfil in (Perfil.ADMIN, Perfil.GESTOR)

    @property
    def pode_disparar_email(self) -> bool:
        return self.is_gestor or bool(self.pode_enviar_email)

    @property
    def pode_entrar(self) -> bool:
        return bool(self.ativo) and not self.somente_referencia

    @property
    def nome_completo(self) -> str:
        """Nome com patente/cargo, como aparece no documento."""
        return f"{self.cargo} {self.nome}".strip() if self.cargo else self.nome

    @property
    def iniciais(self) -> str:
        partes = [p for p in (self.nome or "").split() if p]
        if not partes:
            return "??"
        return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()

    def __repr__(self) -> str:
        return f"<User {self.email}>"


# =====================================================================
# RDM
# =====================================================================
class RDM(db.Model):
    __tablename__ = "rdm"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, index=True)

    # Identificação
    titulo = db.Column(db.String(200), nullable=False)
    solicitante_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    revisor_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
    sistema = db.Column(db.String(150))
    modulo = db.Column(db.String(150))
    negocio = db.Column(db.String(150))
    ambiente = db.Column(db.String(60))

    # Impacto e risco
    objetivo = db.Column(db.Text)
    ativos_envolvidos = db.Column(db.Text)
    sistemas_impactados = db.Column(db.Text)
    riscos = db.Column(db.Text)
    criticidade = db.Column(SAEnum(Criticidade), default=Criticidade.MEDIA)
    indisponibilidade = db.Column(db.Boolean, default=False, nullable=False)

    # Janela de manutenção
    tipo_manutencao = db.Column(db.String(60))
    inicio_previsto = db.Column(db.DateTime)
    fim_previsto = db.Column(db.DateTime)
    inicio_real = db.Column(db.DateTime)
    fim_real = db.Column(db.DateTime)
    motivo = db.Column(db.Text)

    # Contingência
    plano_rollback = db.Column(db.Text)
    tempo_rollback_min = db.Column(db.Integer)

    # Autorização
    emergencial = db.Column(db.Boolean, default=False, nullable=False)
    autorizado_por = db.Column(db.String(150))
    autorizado_cargo = db.Column(db.String(150))
    autorizado_email = db.Column(db.String(180))
    autorizado_telefone = db.Column(db.String(40))
    departamento = db.Column(db.String(150))

    # Encerramento
    resultado = db.Column(SAEnum(ResultadoRDM))
    relato_encerramento = db.Column(db.Text)
    rollback_acionado = db.Column(db.Boolean, default=False, nullable=False)
    encerrado_em = db.Column(db.DateTime(timezone=True))
    encerrado_por_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
    encerramento_enviado_em = db.Column(db.DateTime(timezone=True))

    status = db.Column(SAEnum(StatusRDM), default=StatusRDM.RASCUNHO, nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), default=agora, nullable=False)
    atualizado_em = db.Column(db.DateTime(timezone=True), default=agora, onupdate=agora)
    enviado_em = db.Column(db.DateTime(timezone=True))

    solicitante = db.relationship("User", foreign_keys=[solicitante_id])
    revisor = db.relationship("User", foreign_keys=[revisor_id])
    encerrado_por = db.relationship("User", foreign_keys=[encerrado_por_id])
    atividades = db.relationship(
        "Atividade",
        back_populates="rdm",
        cascade="all, delete-orphan",
        order_by="Atividade.ordem",
    )
    logs = db.relationship(
        "LogRDM",
        back_populates="rdm",
        cascade="all, delete-orphan",
        order_by="LogRDM.criado_em.desc()",
    )

    # ---------------- derivados ----------------
    @property
    def identificador(self) -> str:
        return self.numero or f"RDM-{self.id:04d}"

    @property
    def duracao_prevista_min(self) -> int:
        """Soma das durações das atividades — a janela não é chute."""
        return sum(a.duracao_min or 0 for a in self.atividades)

    @property
    def duracao_formatada(self) -> str:
        total = self.duracao_prevista_min
        if not total:
            return "—"
        h, m = divmod(total, 60)
        if h and m:
            return f"{h}h{m:02d}"
        return f"{h}h" if h else f"{m} min"

    @property
    def duracao_real_min(self) -> int | None:
        """Minutos efetivamente gastos, quando início e fim reais estão preenchidos."""
        if not self.inicio_real or not self.fim_real:
            return None
        return max(int((self.fim_real - self.inicio_real).total_seconds() // 60), 0)

    @staticmethod
    def _formatar_minutos(total: int | None) -> str:
        if not total:
            return "—"
        h, m = divmod(total, 60)
        if h and m:
            return f"{h}h{m:02d}"
        return f"{h}h" if h else f"{m} min"

    @property
    def duracao_real_formatada(self) -> str:
        return self._formatar_minutos(self.duracao_real_min)

    @property
    def desvio_min(self) -> int | None:
        """Diferença entre o tempo real e o previsto. Positivo = estourou a janela."""
        real = self.duracao_real_min
        if real is None or not self.duracao_prevista_min:
            return None
        return real - self.duracao_prevista_min

    @property
    def desvio_formatado(self) -> str:
        desvio = self.desvio_min
        if desvio is None:
            return "—"
        if desvio == 0:
            return "dentro do previsto"
        sinal = "acima" if desvio > 0 else "abaixo"
        return f"{self._formatar_minutos(abs(desvio))} {sinal} do previsto"

    @property
    def encerrada(self) -> bool:
        return self.resultado is not None

    @property
    def atividades_com_falha(self) -> list:
        return [a for a in self.atividades if a.status == StatusAtividade.FALHOU]

    @property
    def equipes_envolvidas(self) -> list[Equipe]:
        vistas, saida = set(), []
        for a in self.atividades:
            if a.equipe and a.equipe not in vistas:
                vistas.add(a.equipe)
                saida.append(a.equipe)
        return saida

    def atividades_por_equipe(self) -> dict:
        agrupado: dict[Equipe, list] = {}
        for a in self.atividades:
            agrupado.setdefault(a.equipe, []).append(a)
        return agrupado

    @property
    def analistas(self) -> list:
        vistos, saida = set(), []
        for a in self.atividades:
            nome = a.nome_analista
            if nome and nome not in vistos:
                vistos.add(nome)
                saida.append(nome)
        return saida

    @property
    def editavel(self) -> bool:
        return self.status in (StatusRDM.RASCUNHO, StatusRDM.ABERTA, StatusRDM.EM_ANALISE)

    def __repr__(self) -> str:
        return f"<RDM {self.identificador}>"


class Atividade(db.Model):
    """Uma linha do plano de trabalho, pertencente a uma equipe e a um analista."""

    __tablename__ = "atividade"

    id = db.Column(db.Integer, primary_key=True)
    rdm_id = db.Column(db.Integer, db.ForeignKey("rdm.id"), nullable=False, index=True)

    equipe = db.Column(SAEnum(Equipe), nullable=False)
    ordem = db.Column(db.Integer, default=1, nullable=False)
    descricao = db.Column(db.Text, nullable=False)

    analista_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
    analista_nome = db.Column(db.String(150))  # para analista externo à base

    duracao_min = db.Column(db.Integer, default=0)
    rollback = db.Column(db.Text)
    status = db.Column(
        SAEnum(StatusAtividade), default=StatusAtividade.PENDENTE, nullable=False
    )
    observacao = db.Column(db.Text)

    rdm = db.relationship("RDM", back_populates="atividades")
    analista = db.relationship("User")

    @property
    def nome_analista(self) -> str:
        if self.analista:
            return self.analista.nome_completo
        return self.analista_nome or "Não atribuído"

    @property
    def duracao_formatada(self) -> str:
        if not self.duracao_min:
            return "—"
        h, m = divmod(self.duracao_min, 60)
        if h and m:
            return f"{h}h{m:02d}"
        return f"{h}h" if h else f"{m} min"


class CatalogoAtividade(db.Model):
    """Atividades recorrentes por equipe, para não redigitar a cada RDM."""

    __tablename__ = "catalogo_atividade"

    id = db.Column(db.Integer, primary_key=True)
    equipe = db.Column(SAEnum(Equipe), nullable=False, index=True)
    descricao = db.Column(db.Text, nullable=False)
    duracao_min = db.Column(db.Integer, default=30)
    rollback = db.Column(db.Text)
    ativo = db.Column(db.Boolean, default=True, nullable=False)


class LogRDM(db.Model):
    __tablename__ = "log_rdm"

    id = db.Column(db.Integer, primary_key=True)
    rdm_id = db.Column(db.Integer, db.ForeignKey("rdm.id"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
    usuario_nome = db.Column(db.String(150))
    acao = db.Column(db.String(60))
    descricao = db.Column(db.Text)
    criado_em = db.Column(db.DateTime(timezone=True), default=agora, nullable=False)

    rdm = db.relationship("RDM", back_populates="logs")


# =====================================================================
# Crise
# =====================================================================
class Crise(db.Model):
    __tablename__ = "crise"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    problema = db.Column(db.Text, nullable=False)
    local = db.Column(db.String(150))
    origem = db.Column(db.String(150))
    criticidade = db.Column(SAEnum(Criticidade), default=Criticidade.ALTA)
    status = db.Column(db.String(30), default="Aberta", nullable=False)
    causa_raiz = db.Column(db.Text)
    solucao = db.Column(db.Text)

    aberta_por_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
    criado_em = db.Column(db.DateTime(timezone=True), default=agora, nullable=False)
    encerrado_em = db.Column(db.DateTime(timezone=True))

    aberta_por = db.relationship("User")
    logs = db.relationship(
        "LogCrise",
        back_populates="crise",
        cascade="all, delete-orphan",
        order_by="LogCrise.criado_em.desc()",
    )

    @property
    def identificador(self) -> str:
        return f"CRISE-{self.id:04d}"


class LogCrise(db.Model):
    __tablename__ = "log_crise"

    id = db.Column(db.Integer, primary_key=True)
    crise_id = db.Column(db.Integer, db.ForeignKey("crise.id"), nullable=False, index=True)
    usuario_nome = db.Column(db.String(150))
    descricao = db.Column(db.Text)
    criado_em = db.Column(db.DateTime(timezone=True), default=agora, nullable=False)

    crise = db.relationship("Crise", back_populates="logs")


# =====================================================================
# Auditoria de acesso (exigência de trilha para órgão público)
# =====================================================================
class LogAcesso(db.Model):
    __tablename__ = "log_acesso"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(180), index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"))
    evento = db.Column(db.String(40))  # LOGIN_OK, LOGIN_FALHA, LOGOUT, BLOQUEIO...
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    detalhe = db.Column(db.String(255))
    criado_em = db.Column(db.DateTime(timezone=True), default=agora, nullable=False)
