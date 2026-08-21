"""Abre todas as telas do sistema e falha se alguma quebrar.

Erros de template (bloco duplicado, variável inexistente, macro errada) só
aparecem no momento em que a página é renderizada. Este teste percorre todas
as rotas de leitura para que nenhuma delas chegue quebrada ao usuário.
"""

from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import (
    RDM,
    Atividade,
    CatalogoAtividade,
    Crise,
    Equipe,
    Perfil,
    ResultadoRDM,
    StatusRDM,
    User,
)

SENHA = "Janela@2026!ok"
falhas = []

app = create_app("testing")

with app.app_context():
    db.create_all()

    admin = User(
        nome="Fernanda Lopes", cargo="Analista",
        email="fernanda.lopes@exemplo.com.br", perfil=Perfil.ADMIN, pode_enviar_email=True,
    )
    admin.definir_senha(SENHA)

    analista = User(
        nome="Ana", cargo="Analista", email="ana@exemplo.com.br",
        perfil=Perfil.ANALISTA, equipe=Equipe.FRONTEND,
    )
    analista.definir_senha(SENHA)

    autoridade = User(
        nome="Roberto Alves", cargo="Ten Cel",
        email="roberto.alves@exemplo.com.br", perfil=Perfil.GESTOR,
        somente_referencia=True,
    )
    autoridade.definir_senha(SENHA)

    db.session.add_all([admin, analista, autoridade])
    db.session.add(
        CatalogoAtividade(equipe=Equipe.BANCO_DADOS, descricao="Backup full", duracao_min=40)
    )
    db.session.commit()

    inicio = datetime.now() + timedelta(days=2)
    rdm = RDM(
        numero="RDM-2026-001", titulo="Atualização do portal", solicitante_id=admin.id,
        revisor_id=admin.id, sistema="Portal", ambiente="Produção",
        objetivo="Aplicar a versão nova.", plano_rollback="Restaurar backup.",
        inicio_previsto=inicio, fim_previsto=inicio + timedelta(hours=2),
        tempo_rollback_min=180, autorizado_por="Ten Cel Roberto Alves",
        status=StatusRDM.ABERTA,
    )
    rdm.atividades.append(
        Atividade(equipe=Equipe.BACKEND, ordem=1, descricao="Deploy",
                  analista_id=analista.id, duracao_min=150)
    )
    db.session.add(rdm)

    crise = Crise(titulo="Indisponibilidade do portal", problema="Fora do ar desde as 9h.",
                  aberta_por_id=admin.id)
    db.session.add(crise)
    db.session.commit()

    rdm_id, crise_id, analista_id = rdm.id, crise.id, analista.id

cliente = app.test_client()
cliente.post("/login", data={"email": "fernanda.lopes@exemplo.com.br", "senha": SENHA})


def abrir(rota, esperado=200):
    try:
        resposta = cliente.get(rota)
        codigo = resposta.status_code
    except Exception as exc:  # noqa: BLE001
        falhas.append(f"{rota} -> {type(exc).__name__}: {exc}")
        print(f"  QUEBROU  {rota}\n           {type(exc).__name__}: {exc}")
        return
    ok = codigo == esperado
    if not ok:
        falhas.append(f"{rota} -> HTTP {codigo}, esperado {esperado}")
    print(f"  {'ok   ' if ok else 'FALHA'}  {rota} [{codigo}]")


print("\nTelas do sistema")
abrir("/")
abrir("/rdm/")
abrir("/rdm/?q=portal&status=ABERTA")
abrir("/rdm/nova")
abrir(f"/rdm/{rdm_id}")
abrir(f"/rdm/{rdm_id}/editar")
abrir(f"/rdm/{rdm_id}/encerrar")
abrir(f"/rdm/{rdm_id}/email")
abrir("/crises/")
abrir("/crises/nova")
abrir(f"/crises/{crise_id}")

print("\nAdministração")
abrir("/admin/usuarios")
abrir("/admin/usuarios/novo")
abrir(f"/admin/usuarios/{analista_id}/editar")
abrir("/admin/catalogo")
abrir("/admin/auditoria")

print("\nConta e acesso")
abrir("/alterar-senha")
abrir("/esqueci-senha")
abrir("/redefinir-senha/token-invalido", esperado=302)

print("\nPáginas de erro")
abrir("/rota-que-nao-existe", esperado=404)
abrir("/rdm/99999", esperado=404)

print("\nTelas com a RDM já encerrada")
with app.app_context():
    r = db.session.get(RDM, rdm_id)
    r.resultado = ResultadoRDM.ROLLBACK
    r.rollback_acionado = True
    r.inicio_real = r.inicio_previsto
    r.fim_real = r.inicio_previsto + timedelta(hours=3, minutes=20)
    r.relato_encerramento = "Rollback acionado após falha na validação."
    r.encerrado_por_id = 1
    r.encerrado_em = datetime.now()
    r.status = StatusRDM.EXECUTADA
    db.session.commit()

abrir(f"/rdm/{rdm_id}")
abrir(f"/rdm/{rdm_id}/encerrar")
abrir(f"/rdm/{rdm_id}/email?tipo=encerramento")
abrir("/")

print()
if falhas:
    print(f"{len(falhas)} tela(s) com problema:")
    for f in falhas:
        print("  -", f)
    raise SystemExit(1)
print("Todas as telas renderizaram.")
