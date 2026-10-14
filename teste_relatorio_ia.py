"""Testa a configuração segura e a geração de relatório por métricas agregadas."""

from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import (
    ConfiguracaoIA,
    Crise,
    Criticidade,
    Perfil,
    RDM,
    StatusRDM,
    User,
)
from app.services.relatorio_ia_service import (
    ErroConfiguracaoIA,
    _url_publica_https,
    decifrar_api_key,
)
from app.services.pdf_service import gerar_pdf_relatorio_ia

SENHA = "Janela@2026!ok"
API_KEY = "sk-test-secret"
falhas = []


def checar(descricao, condicao):
    print(f"  {'ok   ' if condicao else 'FALHA'}  {descricao}")
    if not condicao:
        falhas.append(descricao)


app = create_app("testing")

with app.app_context():
    db.create_all()
    admin = User(
        nome="Admin de Teste",
        email="admin@exemplo.com.br",
        perfil=Perfil.ADMIN,
    )
    admin.definir_senha(SENHA)
    analista = User(
        nome="Analista de Teste",
        email="analista@exemplo.com.br",
        perfil=Perfil.ANALISTA,
    )
    analista.definir_senha(SENHA)
    db.session.add_all([admin, analista])
    db.session.flush()
    db.session.add(
        Crise(
            titulo="TITULO PRIVADO DA CRISE",
            problema="DESCRICAO PRIVADA DA CRISE",
            criticidade=Criticidade.ALTA,
            status="Aberta",
        )
    )
    db.session.add(
        RDM(
            numero="RDM-2026-001",
            titulo="RDM de teste",
            solicitante_id=admin.id,
            plano_rollback="Teste",
            status=StatusRDM.ABERTA,
        )
    )
    db.session.commit()

cliente = app.test_client()
cliente.post("/login", data={"email": "admin@exemplo.com.br", "senha": SENHA})
resposta = cliente.post(
    "/admin/relatorios-ia",
    data={"provedor": "openai", "api_key": API_KEY, "modelo": "gpt-4o-mini"},
)
checar("administrador consegue salvar a integração", resposta.status_code == 302)

with app.app_context():
    configuracao = db.session.get(ConfiguracaoIA, 1)
    checar("chave fica cifrada no banco", configuracao.api_key_cifrada != API_KEY)
    checar("chave pode ser decifrada para uso na integração",
           decifrar_api_key(configuracao) == API_KEY)

pagina_config = cliente.get("/admin/relatorios-ia").get_data(as_text=True)
checar("a chave não é exibida após ser salva", API_KEY not in pagina_config)
checar(
    "a configuração carrega o seletor de provedores e o script local",
    'id="provedor"' in pagina_config and "/static/js/relatorios_ia.js" in pagina_config,
)

cliente.get("/logout")
cliente.post("/login", data={"email": "analista@exemplo.com.br", "senha": SENHA})
resposta = cliente.get("/admin/relatorios-ia")
checar("configuração da API é restrita a administradores", resposta.status_code == 403)
cliente.get("/logout")
cliente.post("/login", data={"email": "admin@exemplo.com.br", "senha": SENHA})


class RespostaFalsa:
    ok = True
    status_code = 200

    def __init__(self, conteudo):
        self.conteudo = conteudo

    def json(self):
        return self.conteudo


chamadas = []
pdfs_gerados = []


def gerar_pdf_falso(ano, relatorio, metricas):
    pdfs_gerados.append((ano, relatorio, metricas))
    return b"%PDF-relatorio-de-teste"


def post_falso(url, **kwargs):
    chamadas.append((url, kwargs))
    if url.endswith("/messages"):
        corpo = {"content": [{"type": "text", "text": "Resumo gerencial de teste."}]}
    elif url.endswith(":generateContent"):
        corpo = {
            "candidates": [
                {"content": {"parts": [{"text": "Resumo gerencial de teste."}]}}
            ]
        }
    else:
        corpo = {"choices": [{"message": {"content": "Resumo gerencial de teste."}}]}
    return RespostaFalsa(corpo)


with patch("app.services.relatorio_ia_service.requests.post", side_effect=post_falso):
    with patch("app.blueprints.painel.gerar_pdf_relatorio_ia", side_effect=gerar_pdf_falso):
        resposta = cliente.post(
            "/indicadores/relatorio-ia",
            data={"ano": "2026"},
        )

checar(
    "gerar relatório baixa um PDF após receber a resposta da IA",
    resposta.status_code == 200
    and resposta.mimetype == "application/pdf"
    and "attachment; filename=relatorio-gerencial-2026.pdf"
    in resposta.headers.get("Content-Disposition", "")
    and resposta.get_data() == b"%PDF-relatorio-de-teste"
    and pdfs_gerados[-1][1] == "Resumo gerencial de teste.",
)
checar(
    "PDF recebe métricas agregadas do ano para incluir gráficos",
    pdfs_gerados[-1][0] == 2026
    and len(pdfs_gerados[-1][2]["crises"]["criadas_no_ano_por_mes"]) == 12
    and len(pdfs_gerados[-1][2]["rdms"]["criadas_no_ano_por_mes"]) == 12,
)

html_relatorio = []


class RenderizadorPDFFalso:
    def __init__(self, string, base_url):
        html_relatorio.append(string)

    def write_pdf(self):
        return b"%PDF-conteudo-do-relatorio"


with app.app_context():
    with patch("weasyprint.HTML", RenderizadorPDFFalso):
        pdf_teste = gerar_pdf_relatorio_ia(
            pdfs_gerados[-1][0],
            pdfs_gerados[-1][1],
            pdfs_gerados[-1][2],
        )
checar(
    "template inclui análise sem recomendações e cinco gráficos SVG",
    pdf_teste.startswith(b"%PDF-")
    and "Resumo gerencial de teste." in html_relatorio[-1]
    and html_relatorio[-1].count("<svg") == 5
    and html_relatorio[-1].count('class="grafico-barras-svg"') == 3
    and "recomenda" not in html_relatorio[-1].lower()
    and "Criticidade das crises abertas" in html_relatorio[-1],
)
checar("requisição usa somente o endpoint OpenAI esperado",
       len(chamadas) == 1 and chamadas[0][0] ==
       "https://api.openai.com/v1/chat/completions")
if chamadas:
    payload = chamadas[0][1]["json"]
    texto_enviado = payload["messages"][1]["content"]
    checar("não envia título nem descrição da crise",
           "TITULO PRIVADO DA CRISE" not in texto_enviado and
           "DESCRICAO PRIVADA DA CRISE" not in texto_enviado)
    checar(
        "instrução da IA exclui sugestões e recomendações",
        "não inclua sugestões, recomendações" in
        payload["messages"][0]["content"].lower(),
    )
    checar("autentica a chamada com a chave configurada",
           chamadas[0][1]["headers"]["Authorization"] == f"Bearer {API_KEY}")

resposta = cliente.post(
    "/admin/relatorios-ia",
    data={"provedor": "anthropic", "modelo": "claude-3-5-sonnet-latest"},
)
checar("exige a chave correspondente ao trocar de provedor", resposta.status_code == 400)

if chamadas:
    casos_provedor = [
        ("anthropic", "claude-3-5-sonnet-latest", "https://api.anthropic.com/v1/messages"),
        (
            "gemini",
            "gemini-3.8-flash",
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.8-flash:generateContent",
        ),
    ]
    for provedor, modelo, url_esperada in casos_provedor:
        cliente.post(
            "/admin/relatorios-ia",
            data={"provedor": provedor, "api_key": API_KEY, "modelo": modelo},
        )
        with patch("app.services.relatorio_ia_service.requests.post", side_effect=post_falso):
            with patch("app.blueprints.painel.gerar_pdf_relatorio_ia", side_effect=gerar_pdf_falso):
                resposta = cliente.post("/indicadores/relatorio-ia", data={"ano": "2026"})
        checar(
            f"{provedor} gera PDF usando endpoint e formato próprios",
            resposta.status_code == 200
            and resposta.mimetype == "application/pdf"
            and pdfs_gerados[-1][1] == "Resumo gerencial de teste."
            and chamadas[-1][0] == url_esperada,
        )
        if provedor == "anthropic":
            checar(
                "Claude recebe chave no header próprio",
                chamadas[-1][1]["headers"].get("x-api-key") == API_KEY,
            )
        else:
            checar(
                "Gemini recebe chave no header próprio",
                chamadas[-1][1]["headers"].get("x-goog-api-key") == API_KEY,
            )

    cliente.post(
        "/admin/relatorios-ia",
        data={
            "provedor": "openai_compatible",
            "api_key": API_KEY,
            "modelo": "llama-3.3-70b-versatile",
            "url_compativel": "https://api.groq.com/openai/v1",
        },
    )
    with patch(
        "app.services.relatorio_ia_service.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("8.8.8.8", 443))],
    ):
        with patch("app.services.relatorio_ia_service.requests.post", side_effect=post_falso):
            with patch("app.blueprints.painel.gerar_pdf_relatorio_ia", side_effect=gerar_pdf_falso):
                resposta = cliente.post("/indicadores/relatorio-ia", data={"ano": "2026"})
    checar(
        "endpoint compatível gera PDF usando Chat Completions",
        resposta.status_code == 200
        and resposta.mimetype == "application/pdf"
        and chamadas[-1][0] == "https://api.groq.com/openai/v1/chat/completions",
    )

    cliente.post(
        "/admin/relatorios-ia",
        data={"provedor": "gemini", "api_key": API_KEY, "modelo": "modelo-inexistente"},
    )


    class Resposta404:
        ok = False
        status_code = 404

        def json(self):
            return {
                "error": {
                    "message": f"models/modelo-inexistente not found; token {API_KEY}"
                }
            }


    with patch(
        "app.services.relatorio_ia_service.requests.post",
        return_value=Resposta404(),
    ):
        resposta = cliente.post(
            "/indicadores/relatorio-ia",
            data={"ano": "2026"},
            follow_redirects=True,
        )
    pagina_erro = resposta.get_data(as_text=True)
    checar(
        "erro 404 do Gemini explica que modelo/projeto precisa ser verificado",
        "modelo-inexistente" in pagina_erro
        and "generateContent" in pagina_erro
        and "Detalhe do provedor" in pagina_erro,
    )
    checar("diagnóstico do 404 nunca revela a chave da API", API_KEY not in pagina_erro)

    class Resposta503:
        ok = False
        status_code = 503
        headers = {"Retry-After": "2"}

    cliente.post(
        "/admin/relatorios-ia",
        data={"provedor": "gemini", "api_key": API_KEY, "modelo": "gemini-3.8-flash"},
    )
    resposta_sucesso = RespostaFalsa(
        {"candidates": [{"content": {"parts": [{"text": "Relatório após nova tentativa."}]}}]}
    )
    with patch(
        "app.services.relatorio_ia_service.requests.post",
        side_effect=[Resposta503(), resposta_sucesso],
    ) as requisicoes:
        with patch("app.services.relatorio_ia_service.time.sleep") as pausa:
            with patch(
                "app.blueprints.painel.gerar_pdf_relatorio_ia",
                side_effect=gerar_pdf_falso,
            ):
                resposta = cliente.post(
                    "/indicadores/relatorio-ia",
                    data={"ano": "2026"},
                )
    checar(
        "Gemini tenta novamente após HTTP 503 e gera o PDF",
        requisicoes.call_count == 2
        and pausa.call_args.args == (2.0,)
        and resposta.status_code == 200
        and resposta.mimetype == "application/pdf"
        and pdfs_gerados[-1][1] == "Relatório após nova tentativa.",
    )

    with patch(
        "app.services.relatorio_ia_service.requests.post",
        return_value=Resposta503(),
    ) as requisicoes:
        with patch("app.services.relatorio_ia_service.time.sleep"):
            resposta = cliente.post(
                "/indicadores/relatorio-ia",
                data={"ano": "2026"},
                follow_redirects=True,
            )
    pagina_erro_503 = resposta.get_data(as_text=True)
    checar(
        "indica indisponibilidade temporária após três respostas HTTP 503",
        requisicoes.call_count == 3
        and "temporariamente indisponível (http 503)" in pagina_erro_503.lower()
        and "tente gerar o relatório novamente" in pagina_erro_503.lower(),
    )

    try:
        with patch(
            "app.services.relatorio_ia_service.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.5", 443))],
        ):
            _url_publica_https("https://interno.exemplo/v1")
    except ErroConfiguracaoIA:
        host_privado_rejeitado = True
    else:
        host_privado_rejeitado = False
    checar("bloqueia endpoint compatível que resolve para IP privado", host_privado_rejeitado)

    print()
if falhas:
    print(f"{len(falhas)} verificação(ões) falharam:")
    for falha in falhas:
        print("  -", falha)
    raise SystemExit(1)
print("Relatórios por IA: todas as verificações passaram.")
