"""Testa o envio de e-mail: seleção do mecanismo, Graph API e falhas.

Não faz chamadas reais à Microsoft — a camada HTTP é substituída por uma
simulação que devolve as respostas que a Graph devolveria.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import RDM, Atividade, Equipe, Perfil, User
from app.services import graph_service
from app.services.email_service import backend_ativo, montar_email_rdm

SENHA = "Janela@2026!ok"
falhas = []


def checar(descricao, condicao):
    print(f"  {'ok   ' if condicao else 'FALHA'}  {descricao}")
    if not condicao:
        falhas.append(descricao)


class RespostaFalsa:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo or {}
        self.text = str(corpo)

    def json(self):
        return self._corpo


app = create_app("testing")

with app.app_context():
    db.create_all()
    u = User(nome="Fernanda Lopes", email="fernanda.lopes@exemplo.com.br",
             perfil=Perfil.ADMIN, pode_enviar_email=True)
    u.definir_senha(SENHA)
    db.session.add(u)
    db.session.commit()
    usuario_id = u.id

    inicio = datetime.now() + timedelta(days=1)
    rdm = RDM(numero="RDM-2026-001", titulo="Atualização do portal",
              solicitante_id=u.id, plano_rollback="Restaurar backup.",
              inicio_previsto=inicio, fim_previsto=inicio + timedelta(hours=2))
    rdm.atividades.append(
        Atividade(equipe=Equipe.BACKEND, ordem=1, descricao="Deploy",
                  analista_id=u.id, duracao_min=60)
    )
    db.session.add(rdm)
    db.session.commit()
    rdm_id = rdm.id

print("\nFormatação de data e hora")
with app.app_context():
    filtro_dt = app.jinja_env.filters["dt"]
    checar(
        "datetime sem tz vindo do SQLite é tratado como UTC e convertido para Brasília",
        filtro_dt(datetime(2026, 8, 28, 15, 0)) == "28/08/2026 12:00",
    )
    checar(
        "datetime UTC é convertido para horário de Brasília",
        filtro_dt(datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)) == "28/08/2026 09:00",
    )

    usuario = db.session.get(User, usuario_id)
    rdm_teste = RDM(
        numero="RDM-2026-002",
        titulo="Teste de horário de e-mail",
        solicitante_id=usuario.id,
        inicio_previsto=datetime(2026, 8, 28, 15, 0),
        fim_previsto=datetime(2026, 8, 28, 17, 0),
    )
    assunto, _, _ = montar_email_rdm(rdm_teste)
    checar(
        "assunto do e-mail usa o horário em Brasília",
        "12:00" in assunto and "15:00" not in assunto,
    )

print("\nEscolha do mecanismo")
with app.app_context():
    cfg = dict(app.config)
    cfg.update({"EMAIL_BACKEND": "auto", "GRAPH_TENANT_ID": "", "GRAPH_CLIENT_ID": "",
                "GRAPH_CLIENT_SECRET": ""})
    checar("sem credenciais da Graph, usa SMTP", backend_ativo(cfg) == "smtp")

    cfg.update({"GRAPH_TENANT_ID": "t", "GRAPH_CLIENT_ID": "c", "GRAPH_CLIENT_SECRET": "s"})
    checar("com credenciais da Graph, usa Graph", backend_ativo(cfg) == "graph")

    cfg["EMAIL_BACKEND"] = "smtp"
    checar("EMAIL_BACKEND=smtp força SMTP", backend_ativo(cfg) == "smtp")

    cfg["EMAIL_BACKEND"] = "graph"
    cfg["GRAPH_TENANT_ID"] = ""
    checar("EMAIL_BACKEND=graph força Graph", backend_ativo(cfg) == "graph")

print("\nEnvio pela Graph")
CFG_GRAPH = {
    "EMAIL_BACKEND": "graph",
    "GRAPH_TENANT_ID": "tenant-teste",
    "GRAPH_CLIENT_ID": "cliente-teste",
    "GRAPH_CLIENT_SECRET": "segredo-teste",
    "EMAIL_REMETENTE": "sistema@exemplo.com.br",
}

chamadas = []


def post_falso(url, **kwargs):
    chamadas.append((url, kwargs))
    if "oauth2" in url:
        return RespostaFalsa(200, {"access_token": "token-abc", "expires_in": 3600})
    return RespostaFalsa(202)


graph_service._token_cache["valor"] = None
with patch.object(graph_service.requests, "post", side_effect=post_falso):
    ok, erro = graph_service.enviar_graph(
        ["destino@exemplo.com.br"], "Assunto", "<p>corpo</p>", "corpo", cfg=CFG_GRAPH
    )
checar("envio bem-sucedido retorna ok", ok and not erro)
checar("pediu token ao Entra ID", any("oauth2" in c[0] for c in chamadas))
checar(
    "enviou pela caixa do remetente",
    any("users/sistema@exemplo.com.br/sendMail" in c[0] for c in chamadas),
)

corpo = [c for c in chamadas if "sendMail" in c[0]][0][1]["json"]
checar("assunto vai na mensagem", corpo["message"]["subject"] == "Assunto")
checar(
    "destinatário vai na mensagem",
    corpo["message"]["toRecipients"][0]["emailAddress"]["address"] == "destino@exemplo.com.br",
)
checar("corpo é HTML", corpo["message"]["body"]["contentType"] == "HTML")

print("\nToken é reaproveitado")
chamadas.clear()
with patch.object(graph_service.requests, "post", side_effect=post_falso):
    graph_service.enviar_graph(["a@exemplo.com.br"], "x", "<p>y</p>", "y", cfg=CFG_GRAPH)
checar("segundo envio não pede token de novo", not any("oauth2" in c[0] for c in chamadas))

print("\nErros são explicados")
graph_service._token_cache["valor"] = None


def post_sem_permissao(url, **kwargs):
    if "oauth2" in url:
        return RespostaFalsa(200, {"access_token": "t", "expires_in": 3600})
    return RespostaFalsa(
        403,
        {"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}},
    )


with patch.object(graph_service.requests, "post", side_effect=post_sem_permissao):
    ok, erro = graph_service.enviar_graph(
        ["a@exemplo.com.br"], "x", "<p>y</p>", "y", cfg=CFG_GRAPH
    )
checar("falha de permissão retorna erro", not ok)
checar("erro explica a permissão Mail.Send", "Mail.Send" in erro)

graph_service._token_cache["valor"] = None


def post_segredo_ruim(url, **kwargs):
    return RespostaFalsa(
        401, {"error": "invalid_client", "error_description": "AADSTS7000215: bad secret"}
    )


with patch.object(graph_service.requests, "post", side_effect=post_segredo_ruim):
    ok, erro = graph_service.enviar_graph(
        ["a@exemplo.com.br"], "x", "<p>y</p>", "y", cfg=CFG_GRAPH
    )
checar("segredo inválido é identificado", not ok and "segredo" in erro.lower())

print("\nA tela não mente sobre o envio")
cliente = app.test_client()
cliente.post("/login", data={"email": "fernanda.lopes@exemplo.com.br", "senha": SENHA})

with app.app_context():
    for chave, valor in CFG_GRAPH.items():
        app.config[chave] = valor

graph_service._token_cache["valor"] = None
with patch.object(graph_service.requests, "post", side_effect=post_sem_permissao):
    resposta = cliente.post(
        f"/rdm/{rdm_id}/email/enviar",
        data={"destinatarios": "destino@exemplo.com.br", "introducao": "TEXTO_PRESERVADO"},
        follow_redirects=True,
    )

pagina = resposta.get_data(as_text=True)
checar("falha no envio devolve erro, não sucesso", resposta.status_code == 400)
checar("a tela mostra o motivo real", "não foi enviado" in pagina.lower())
checar("o texto digitado é preservado", "TEXTO_PRESERVADO" in pagina)
checar("não diz que enviou", "e-mail enviado para" not in pagina.lower())

with app.app_context():
    r = db.session.get(RDM, rdm_id)
    checar("a RDM não é marcada como comunicada", r.enviado_em is None)
    checar(
        "a falha fica registrada no histórico",
        any(log.acao == "EMAIL_FALHA" for log in r.logs),
    )

graph_service._token_cache["valor"] = None
with patch.object(graph_service.requests, "post", side_effect=post_falso):
    resposta = cliente.post(
        f"/rdm/{rdm_id}/email/enviar",
        data={"destinatarios": "destino@exemplo.com.br"},
        follow_redirects=True,
    )
checar("envio bem-sucedido confirma na tela", "enviado para" in resposta.get_data(as_text=True).lower())
with app.app_context():
    r = db.session.get(RDM, rdm_id)
    checar("a RDM é marcada como comunicada só no sucesso", r.enviado_em is not None)

print()
if falhas:
    print(f"{len(falhas)} verificação(ões) falharam:")
    for f in falhas:
        print("  -", f)
    raise SystemExit(1)
print("Envio de e-mail: todas as verificações passaram.")
