"""Gera um PDF de exemplo a partir de uma RDM populada, para conferência visual."""

from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import RDM, Atividade, Equipe, Perfil, StatusRDM, User
from app.services.pdf_service import gerar_pdf_rdm

app = create_app("testing")

with app.app_context():
    db.create_all()

    gestor = User(nome="Fernanda Lopes", email="fernanda@exemplo.com.br", perfil=Perfil.ADMIN)
    gestor.definir_senha("Janela@2026!ok")
    revisor = User(nome="Bruno Lima", email="bruno@exemplo.com.br", perfil=Perfil.GESTOR)
    revisor.definir_senha("Janela@2026!ok")
    db.session.add_all([gestor, revisor])
    db.session.commit()

    inicio = datetime.now() + timedelta(days=4)
    rdm = RDM(
        numero="RDM-2026-001",
        titulo="Atualização do portal do beneficiário para a versão 4.2",
        solicitante_id=gestor.id,
        revisor_id=revisor.id,
        sistema="Portal do Beneficiário",
        modulo="Autenticação",
        negocio="Atendimento",
        ambiente="Produção",
        objetivo="Aplicar a versão 4.2, corrigindo a falha de sessão expirada no login.",
        ativos_envolvidos="SRV-WEB-01, SRV-API-02, BD-PROD",
        sistemas_impactados="Portal do beneficiário e aplicativo móvel",
        riscos="Indisponibilidade do login durante a publicação da API.",
        indisponibilidade=True,
        tipo_manutencao="Programada",
        inicio_previsto=inicio.replace(hour=22, minute=0),
        fim_previsto=inicio.replace(hour=23, minute=59),
        motivo="Menor volume de acesso após as 22h.",
        plano_rollback="Restaurar o backup do banco e republicar a release 4.1.",
        tempo_rollback_min=60,
        autorizado_por="Diretor de TI",
        autorizado_cargo="Diretoria de Tecnologia",
        departamento="Tecnologia da Informação",
        status=StatusRDM.APROVADA,
    )
    atividades = [
        (Equipe.INFRAESTRUTURA, "Abrir janela no Zabbix e tirar snapshot das VMs", "Rafael Costa", 20, ""),
        (Equipe.BANCO_DADOS, "Backup full do banco de produção", "João Pereira", 40, "Restore do backup"),
        (Equipe.BACKEND, "Deploy da API 4.2 e validação dos endpoints de login", "Bruno Lima", 45, "Voltar para a release 4.1"),
        (Equipe.FRONTEND, "Publicação do build e limpeza de cache", "Ana", 25, ""),
        (Equipe.INFRAESTRUTURA, "Fechar a janela e validar o monitoramento", "Rafael Costa", 10, ""),
    ]
    for i, (equipe, descricao, analista, duracao, rollback) in enumerate(atividades, 1):
        rdm.atividades.append(
            Atividade(
                equipe=equipe, ordem=i, descricao=descricao,
                analista_nome=analista, duracao_min=duracao, rollback=rollback or None,
            )
        )
    db.session.add(rdm)
    db.session.commit()

    caminho = gerar_pdf_rdm(rdm)
    print(f"PDF gerado: {caminho}")

    # também salva o HTML do e-mail para conferência
    from app.services.email_service import montar_email_rdm

    assunto, html, texto = montar_email_rdm(rdm)
    print(f"Assunto: {assunto}")
    with open("instance/pdfs/preview_email.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open("instance/pdfs/preview_email.txt", "w", encoding="utf-8") as f:
        f.write(texto)
    print("Prévias do e-mail salvas.")
