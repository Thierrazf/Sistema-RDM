"""Teste funcional do fluxo principal: login → criar RDM → detalhe → e-mail."""

from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import CatalogoAtividade, Equipe, Perfil, User

SENHA_PADRAO = "Janela@2026!ok"

app = create_app("testing")

with app.app_context():
    db.create_all()

    gestor = User(nome="Fernanda Lopes", email="fernanda@exemplo.com.br", perfil=Perfil.ADMIN)
    gestor.definir_senha("Janela@2026!ok")
    analista = User(
        nome="João Pereira",
        email="joao@exemplo.com.br",
        perfil=Perfil.ANALISTA,
        equipe=Equipe.BACKEND,
    )
    analista.definir_senha("Janela@2026!ok")
    db.session.add_all([gestor, analista])
    db.session.add(
        CatalogoAtividade(
            equipe=Equipe.BANCO_DADOS, descricao="Backup full antes da alteração", duracao_min=40
        )
    )
    db.session.commit()
    analista_id = analista.id

cliente = app.test_client()

# --- login ------------------------------------------------------------
r = cliente.post(
    "/login",
    data={"email": "fernanda@exemplo.com.br", "senha": "errada"},
    follow_redirects=True,
)
assert b"inv" in r.data.lower(), "deveria recusar senha errada"
print("recusa de senha errada ......... ok")

r = cliente.post(
    "/login",
    data={"email": "fernanda@exemplo.com.br", "senha": "Janela@2026!ok"},
    follow_redirects=True,
)
assert r.status_code == 200 and b"Painel" in r.data, r.status_code
print("login .......................... ok")

# --- criar RDM --------------------------------------------------------
inicio = (datetime.now() + timedelta(days=3)).replace(hour=22, minute=0, second=0, microsecond=0)
fim = inicio + timedelta(hours=3)

dados = {
    "titulo": "Atualização do portal do beneficiário para a versão 4.2",
    "sistema": "Portal do Beneficiário",
    "modulo": "Autenticação",
    "negocio": "Atendimento",
    "ambiente": "Produção",
    "objetivo": "Aplicar a versão 4.2 corrigindo a falha de sessão expirada no login.",
    "ativos_envolvidos": "SRV-WEB-01, SRV-API-02, BD-PROD",
    "sistemas_impactados": "Portal do beneficiário e aplicativo móvel",
    "riscos": "Indisponibilidade do login durante a publicação.",
    "criticidade": "ALTA",
    "indisponibilidade": "on",
    "tipo_manutencao": "Programada",
    "inicio_previsto": inicio.strftime("%Y-%m-%dT%H:%M"),
    "fim_previsto": fim.strftime("%Y-%m-%dT%H:%M"),
    "motivo": "Menor volume de acesso após as 22h.",
    "plano_rollback": "Restaurar o backup do banco e republicar a release 4.1.",
    "tempo_rollback_h": "1",
    "tempo_rollback_m": "30",
    "autorizado_por": "Diretor de TI",
    "autorizado_cargo": "Diretoria de Tecnologia",
    "autorizado_email": "diretoria@exemplo.com.br",
    "departamento": "TI",
    # plano de trabalho — quatro equipes
    "atv_equipe": ["INFRAESTRUTURA", "BANCO_DADOS", "BACKEND", "FRONTEND"],
    "atv_descricao": [
        "Abrir janela no Zabbix e tirar snapshot das VMs",
        "Backup full do banco de produção",
        "Deploy da API 4.2 e validação dos endpoints de login",
        "Publicação do build e limpeza de cache",
    ],
    "atv_analista_id": ["", str(analista_id), str(analista_id), ""],
    "atv_analista_nome": ["Rafael Costa", "", "", "Ana"],
    "atv_duracao_h": ["0", "0", "1", "0"],
    "atv_duracao_m": ["20", "40", "15", "25"],
    "atv_rollback": ["", "Restore do backup", "Voltar para a release 4.1", ""],
}

r = cliente.post("/rdm/nova", data=dados, follow_redirects=True)
assert r.status_code == 200, r.status_code
assert b"RDM-" in r.data, "a RDM deveria ter sido criada"
print("criacao da RDM ................. ok")

with app.app_context():
    from app.models import RDM

    rdm = db.session.query(RDM).first()
    assert rdm.duracao_prevista_min == 160, rdm.duracao_prevista_min  # 20+40+75+25
    assert len(rdm.equipes_envolvidas) == 4, rdm.equipes_envolvidas
    assert rdm.duracao_formatada == "2h40", rdm.duracao_formatada
    assert rdm.tempo_rollback_min == 90, rdm.tempo_rollback_min  # 1h30
    assert rdm.numero.startswith("RDM-"), rdm.numero
    rdm_id = rdm.id
    print(f"  numero {rdm.numero} · {len(rdm.atividades)} atividades · {rdm.duracao_formatada}")
print("calculo da janela .............. ok")

# --- detalhe ----------------------------------------------------------
r = cliente.get(f"/rdm/{rdm_id}")
assert r.status_code == 200
assert "Infraestrutura".encode() in r.data
assert "Banco de Dados".encode() in r.data
assert "Rafael Costa".encode() in r.data
assert b"janela-bloco" in r.data, "a faixa da janela deveria renderizar"
print("tela de detalhe ................ ok")

# --- pre-visualizacao do e-mail --------------------------------------
r = cliente.get(f"/rdm/{rdm_id}/email")
assert r.status_code == 200, r.status_code
assert "Plano de trabalho".encode() in r.data
assert "joao@exemplo.com.br".encode() in r.data, "deveria sugerir os analistas"
print("preview do e-mail .............. ok")

# --- lista e busca ----------------------------------------------------
r = cliente.get("/rdm/?q=portal")
assert r.status_code == 200 and b"RDM-" in r.data
r = cliente.get("/rdm/?status=CANCELADA")
assert "Nenhuma RDM encontrada".encode() in r.data
print("lista, busca e filtro .......... ok")

# --- permissoes -------------------------------------------------------
cliente.get("/logout")
cliente.post(
    "/login", data={"email": "joao@exemplo.com.br", "senha": "Janela@2026!ok"}
)
r = cliente.get("/admin/usuarios")
assert r.status_code == 403, r.status_code
r = cliente.post(f"/rdm/{rdm_id}/status", data={"status": "APROVADA"})
assert r.status_code == 403, r.status_code
r = cliente.get(f"/rdm/{rdm_id}/email")
assert r.status_code == 403, r.status_code
print("bloqueio por perfil ............ ok")

# --- bloqueio por tentativas -----------------------------------------
cliente.get("/logout")
for _ in range(5):
    cliente.post("/login", data={"email": "joao@exemplo.com.br", "senha": "x"})
r = cliente.post(
    "/login", data={"email": "joao@exemplo.com.br", "senha": "Janela@2026!ok"}
)
assert "bloqueada".encode() in r.data, "a conta deveria estar bloqueada"
print("bloqueio por tentativas ........ ok")




# =====================================================================
# Encerramento da janela e comunicado de fechamento
# =====================================================================
from app.models import ResultadoRDM, StatusRDM  # noqa: E402

cliente.get("/logout")
cliente.post(
    "/login", data={"email": "fernanda@exemplo.com.br", "senha": "Janela@2026!ok"}
)

# analista não pode encerrar
r = cliente.get(f"/rdm/{rdm_id}/encerrar")
assert r.status_code == 200, r.status_code
print("tela de encerramento ........... ok")

# validação: fim anterior ao início é recusado
r = cliente.post(
    f"/rdm/{rdm_id}/encerrar",
    data={
        "resultado": "SUCESSO",
        "inicio_real": inicio.strftime("%Y-%m-%dT%H:%M"),
        "fim_real": (inicio - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        "relato_encerramento": "Executado sem intercorrencias.",
    },
)
assert r.status_code == 400, r.status_code
assert "posterior".encode() in r.data
print("valida fim anterior ao inicio .. ok")

# encerramento com rollback
fim_real = inicio + timedelta(hours=2, minutes=45)
with app.app_context():
    atividades_ids = [a.id for a in db.session.get(RDM, rdm_id).atividades]

dados_encerramento = {
    "resultado": "ROLLBACK",
    "inicio_real": inicio.strftime("%Y-%m-%dT%H:%M"),
    "fim_real": fim_real.strftime("%Y-%m-%dT%H:%M"),
    "relato_encerramento": "Falha na validacao dos endpoints. Rollback acionado as 23h40.",
}
for i, aid in enumerate(atividades_ids):
    dados_encerramento[f"atividade_{aid}"] = "FALHOU" if i == 2 else "EXECUTADA"

r = cliente.post(f"/rdm/{rdm_id}/encerrar", data=dados_encerramento, follow_redirects=True)
assert r.status_code == 200, r.status_code

with app.app_context():
    rdm = db.session.get(RDM, rdm_id)
    assert rdm.resultado == ResultadoRDM.ROLLBACK, rdm.resultado
    assert rdm.rollback_acionado is True, "rollback deveria ser marcado automaticamente"
    assert rdm.duracao_real_min == 165, rdm.duracao_real_min
    assert rdm.duracao_real_formatada == "2h45", rdm.duracao_real_formatada
    assert rdm.desvio_min == 5, rdm.desvio_min
    assert "acima" in rdm.desvio_formatado, rdm.desvio_formatado
    assert len(rdm.atividades_com_falha) == 1, rdm.atividades_com_falha
    assert rdm.status == StatusRDM.EXECUTADA, rdm.status
    print(f"  {rdm.duracao_real_formatada} reais · {rdm.desvio_formatado}")
print("encerramento com rollback ...... ok")

# o comunicado de encerramento usa o texto padrão do desfecho
r = cliente.get(f"/rdm/{rdm_id}/email?tipo=encerramento")
assert r.status_code == 200, r.status_code
assert "rollback".encode() in r.data.lower()
assert "Revertida por rollback".encode() in r.data
assert "2h45".encode() in r.data, "as horas reais devem aparecer"
print("comunicado de encerramento ..... ok")

# o texto padrão muda conforme o resultado
from app.services.email_service import texto_padrao_encerramento  # noqa: E402

assert "NÃO foi concluída" in texto_padrao_encerramento(ResultadoRDM.ROLLBACK)
assert "dentro da janela programada" in texto_padrao_encerramento(ResultadoRDM.SUCESSO)
assert texto_padrao_encerramento(ResultadoRDM.SUCESSO) != texto_padrao_encerramento(
    ResultadoRDM.ROLLBACK
)
print("texto padrao por desfecho ...... ok")

# falha no envio preserva o que foi digitado
r = cliente.post(
    f"/rdm/{rdm_id}/email/enviar",
    data={
        "tipo": "encerramento",
        "destinatarios": "endereco-invalido",
        "introducao": "TEXTO_QUE_NAO_PODE_SUMIR",
        "observacao": "OBSERVACAO_PRESERVADA",
    },
)
assert r.status_code == 400, r.status_code
assert "TEXTO_QUE_NAO_PODE_SUMIR".encode() in r.data, "o texto digitado se perdeu"
assert "OBSERVACAO_PRESERVADA".encode() in r.data, "a observacao se perdeu"
print("formulario preservado na falha . ok")

# atividade sem analista é recusada
dados_sem_analista = dict(dados)
dados_sem_analista["atv_analista_id"] = ["", "", "", ""]
dados_sem_analista["atv_analista_nome"] = ["", "", "", ""]
r = cliente.post("/rdm/nova", data=dados_sem_analista)
assert r.status_code == 400, r.status_code
assert "analista responsável".encode() in r.data
print("exige analista por atividade ... ok")




# =====================================================================
# Pessoas de referência, cargo e tempos em horas
# =====================================================================
with app.app_context():
    from app.models import Perfil as _P

    ten_cel = User(
        nome="Roberto Alves", cargo="Ten Cel",
        email="roberto.alves@exemplo.com.br",
        perfil=_P.GESTOR, somente_referencia=True,
    )
    ten_cel.definir_senha("Janela@2026!ok")
    ten = User(
        nome="Carlos Mendes", cargo="2º Ten",
        email="carlos.mendes@exemplo.com.br",
        perfil=_P.GESTOR, somente_referencia=True,
    )
    ten.definir_senha("Janela@2026!ok")
    db.session.add_all([ten_cel, ten])
    db.session.commit()
    assert ten_cel.nome_completo == "Ten Cel Roberto Alves", ten_cel.nome_completo
    assert ten_cel.pode_entrar is False, "pessoa de referência não deve acessar"
    ten_cel_id, ten_id = ten_cel.id, ten.id
print("cadastro de autoridade ......... ok")

# pessoa de referência não consegue entrar, mesmo com a senha certa
cliente.get("/logout")
r = cliente.post(
    "/login",
    data={"email": "roberto.alves@exemplo.com.br", "senha": "Janela@2026!ok"},
)
assert r.status_code == 401, r.status_code
assert "sem acesso".encode() in r.data.lower()
print("referência não faz login ....... ok")

cliente.post("/login", data={"email": "fernanda@exemplo.com.br", "senha": "Janela@2026!ok"})

# a autoridade aparece nos seletores do formulário
r = cliente.get("/rdm/nova")
assert "Ten Cel Roberto Alves".encode() in r.data, "deveria aparecer como autorizador"
assert "2º Ten Carlos Mendes".encode() in r.data
assert b'name="solicitante_id"' in r.data, "solicitante deveria ser seletor"
assert b'name="autorizador_id"' in r.data, "autorizador deveria ser seletor"
print("seletores de pessoas ........... ok")

# criar RDM escolhendo solicitante e autorizador do cadastro
dados_novos = dict(dados)
dados_novos["titulo"] = "Restore completo da base de produção"
dados_novos["solicitante_id"] = str(ten_id)
dados_novos["autorizador_id"] = str(ten_cel_id)
dados_novos["atv_duracao_h"] = ["2", "1", "0", "0"]   # rollback longo, como no restore
dados_novos["atv_duracao_m"] = ["30", "0", "45", "15"]
dados_novos["tempo_rollback_h"] = "3"
dados_novos["tempo_rollback_m"] = "0"

r = cliente.post("/rdm/nova", data=dados_novos, follow_redirects=True)
assert r.status_code == 200, r.status_code

with app.app_context():
    nova = db.session.query(RDM).order_by(RDM.id.desc()).first()
    assert nova.solicitante_id == ten_id, nova.solicitante_id
    assert nova.solicitante.nome_completo == "2º Ten Carlos Mendes"
    assert nova.autorizado_por == "Ten Cel Roberto Alves", nova.autorizado_por
    assert nova.autorizado_cargo == "Ten Cel", nova.autorizado_cargo
    assert nova.autorizado_email == "roberto.alves@exemplo.com.br"
    assert nova.duracao_prevista_min == 270, nova.duracao_prevista_min  # 150+60+45+15
    assert nova.duracao_formatada == "4h30", nova.duracao_formatada
    assert nova.tempo_rollback_min == 180, nova.tempo_rollback_min  # 3h
    print(f"  janela de {nova.duracao_formatada}, rollback de 3h")
print("tempos em horas e minutos ...... ok")




# =====================================================================
# Cadastro de usuários pela administração
# =====================================================================
r = cliente.get("/admin/usuarios/novo")
assert r.status_code == 200, r.status_code
assert b"somente_referencia" in r.data
print("tela de novo usuario ........... ok")

# senha fraca é recusada
r = cliente.post(
    "/admin/usuarios/novo",
    data={"nome": "Fulano de Tal", "email": "fulano@exemplo.com.br",
          "perfil": "ANALISTA", "senha": "12345678"},
)
assert r.status_code == 400, r.status_code
assert "senha precisa".encode() in r.data
print("recusa senha fraca ............. ok")

# domínio fora da lista é recusado
r = cliente.post(
    "/admin/usuarios/novo",
    data={"nome": "Fulano de Tal", "email": "fulano@gmail.com",
          "perfil": "ANALISTA", "senha": SENHA_PADRAO},
)
assert r.status_code == 400, r.status_code
assert "corporativos".encode() in r.data
print("recusa dominio externo ......... ok")

# criação válida de analista
r = cliente.post(
    "/admin/usuarios/novo",
    data={"nome": "Ana Souza", "cargo": "Analista", "email": "ana@exemplo.com.br",
          "perfil": "ANALISTA", "equipe": "FRONTEND", "senha": SENHA_PADRAO},
    follow_redirects=True,
)
assert r.status_code == 200, r.status_code
with app.app_context():
    nova = db.session.query(User).filter_by(email="ana@exemplo.com.br").first()
    assert nova is not None, "usuário não foi criado"
    assert nova.trocar_senha is True, "deveria exigir troca no primeiro acesso"
    assert nova.nome_completo == "Analista Ana Souza"
print("cria analista .................. ok")

# a troca de senha é exigida no primeiro acesso
cliente.get("/logout")
r = cliente.post(
    "/login",
    data={"email": "ana@exemplo.com.br", "senha": SENHA_PADRAO},
    follow_redirects=True,
)
assert "nova senha".encode() in r.data.lower(), "deveria exigir troca de senha"
print("exige troca no 1o acesso ....... ok")

cliente.get("/logout")
cliente.post("/login", data={"email": "fernanda@exemplo.com.br", "senha": SENHA_PADRAO})

# pessoa de referência é criada sem senha
r = cliente.post(
    "/admin/usuarios/novo",
    data={"nome": "Carlos Mendes", "cargo": "2º Ten",
          "email": "carlos.m@exemplo.com.br", "perfil": "GESTOR",
          "somente_referencia": "on"},
    follow_redirects=True,
)
assert r.status_code == 200, r.status_code
with app.app_context():
    pessoa = db.session.query(User).filter_by(email="carlos.m@exemplo.com.br").first()
    assert pessoa is not None, "pessoa de referência não foi criada"
    assert pessoa.somente_referencia is True
    assert pessoa.pode_entrar is False
print("cria referencia sem senha ...... ok")

print("\nTodos os testes passaram.")
