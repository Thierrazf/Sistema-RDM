# Gestão de Mudanças — RDM e Crises

Sistema web para registrar Requisições de Mudança (RDM), montar o plano de
trabalho dividido entre as equipes de infraestrutura, front-end, back-end e
banco de dados, e comunicar a mudança por e-mail com o PDF anexado.

Substitui o fluxo em Word + PDF com disparo manual.

---

## O que o sistema faz

- **RDM em 4 etapas** — identificação, impacto e risco, janela e plano de
  trabalho, autorização.
- **Plano de trabalho por equipe** — cada atividade tem equipe, ordem de
  execução, analista responsável, duração e rollback próprio. A duração da
  janela é a soma real das atividades, não um campo digitado.
- **Catálogo de atividades recorrentes** — o analista escolhe do seletor em vez
  de redigitar o que se repete a cada janela.
- **Comunicação por e-mail** — texto padrão editável por envio,
  pré-visualização do que será recebido, destinatários sugeridos a partir dos
  analistas das atividades, e PDF em anexo.
- **Crises** — registro, linha do tempo e comunicado.
- **Trilha de acesso** — login, falha, bloqueio, logout e reset com IP e
  user-agent, para atender auditoria.

---

## Instalação (desenvolvimento)

```bash
git clone <url-do-repositorio>
cd rdm-sistema

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # Windows: copy .env.example .env
```

Gere uma chave e coloque em `SECRET_KEY` no `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Crie o banco e o primeiro administrador:

```bash
export FLASK_APP=wsgi.py        # Windows: set FLASK_APP=wsgi.py

flask db init                   # só na primeira vez
flask db migrate -m "estrutura inicial"
flask db upgrade

flask criar-admin --email seu.email@exemplo.com.br --nome "Seu Nome"
flask carregar-pessoas          # autoridades que assinam a RDM
flask carregar-catalogo         # 21 atividades padrão das 4 equipes
```

Suba a aplicação:

```bash
flask run --debug
```

Acesse `http://127.0.0.1:5000`.

### WeasyPrint no Windows

A geração de PDF depende das bibliotecas GTK. No Windows, instale o
[GTK3 Runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)
e reinicie o terminal. No Linux:

```bash
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev
```

---

## Produção

Nunca use `flask run` nem `debug=True` em produção.

```bash
export FLASK_ENV=production
gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app
```

Com Docker:

```bash
docker compose up -d --build
docker compose exec web flask db upgrade
docker compose exec web flask criar-admin --email seu.email@exemplo.com.br
docker compose exec web flask carregar-catalogo
```

### Exigências antes de publicar

| Item | Por quê |
|---|---|
| `SECRET_KEY` forte no ambiente | A aplicação se recusa a subir sem ela em produção |
| `FLASK_ENV=production` | Ativa `SESSION_COOKIE_SECURE` e HSTS |
| HTTPS no proxy (nginx/IIS) | O cookie de sessão só trafega em conexão segura |
| PostgreSQL em vez de SQLite | Concorrência de escrita e backup consistente |
| `RATELIMIT_STORAGE_URI` com Redis | Com mais de um worker, o limite em memória não é compartilhado |
| Conta SMTP dedicada | Não reutilize a caixa funcional de uma pessoa |
| Rotina de backup do banco | Trilha de acesso e histórico têm valor de auditoria |

---

## Pessoas da RDM

Solicitante, revisor técnico, analista das atividades e autorizador saem todos
do cadastro de usuários — não são mais campos de texto livre.

Quem assina ou autoriza sem precisar usar o sistema (autoridades da corporação)
é cadastrado com a marcação **"Apenas referência — não acessa o sistema"**:
aparece nos seletores, entra no e-mail e no PDF com a patente, mas não faz login
nem tem senha. O comando `flask carregar-pessoas` já cria as autoridades
iniciais; ajuste os e-mails em Administração → Usuários.

O campo **cargo ou patente** aparece junto do nome em todo lugar
("Ten Cel Roberto Alves", "2º Ten Carlos Mendes").

## Perfis de acesso

| Perfil | Pode |
|---|---|
| **Analista** | Criar e editar as próprias RDMs, registrar andamento e status de atividade |
| **Gestor** | Tudo do analista, mais aprovar/alterar status, enviar comunicados e excluir |
| **Administrador** | Tudo, mais gestão de usuários, catálogo e trilha de acesso |

O envio de e-mail também pode ser liberado individualmente para um analista
pelo campo "Pode disparar comunicados por e-mail".

---

## Estrutura

```
app/
  __init__.py            factory, blueprints, CLI, handlers de erro
  config.py              configuração por ambiente
  extensions.py          db, migrate, csrf, login, limiter
  models.py              User, RDM, Atividade, Catalogo, Crise, LogAcesso
  security.py            decorators, validações, auditoria, cabeçalhos
  blueprints/            auth, painel, rdm, crise, admin
  services/
    email_service.py     montagem e disparo (assíncrono)
    pdf_service.py       WeasyPrint
  templates/
    email/               corpo dos e-mails (HTML + texto)
    pdf/                 documentos A4
  static/css/app.css     design system
wsgi.py
teste_fluxo.py           teste funcional do fluxo principal
teste_pdf.py             gera um PDF de exemplo para conferência
```

---

## Testes

```bash
python teste_fluxo.py     # login, RDM, encerramento, permissões, usuários
python teste_telas.py     # abre todas as telas e falha se alguma quebrar
python teste_seguranca.py # hash de senha, cabeçalhos, CSRF, controle de acesso
python teste_pdf.py       # gera instance/pdfs/RDM-2026-001.pdf
```

Rode os três primeiros depois de qualquer alteração — juntos levam poucos
segundos e pegam a maior parte das regressões.

---

## Personalizar o texto padrão do e-mail

O texto de abertura fica em `app/services/email_service.py`, na constante
`TEXTO_PADRAO_RDM`. O layout do e-mail está em `app/templates/email/rdm.html`
(versão HTML) e `rdm.txt` (texto puro). Quem envia pode ajustar o texto na
tela de pré-visualização — a alteração vale só para aquele disparo.

---

## Correções perante o desenvolvimento do projeto.

- Corrigido o bug que impedia o cadastro de usuários novos e criava duplicados
- Removida a rota `/seed-user`, que expunha um administrador com senha conhecida
- `SECRET_KEY` saiu do código; CSRF, rate limit e bloqueio de conta adicionados
- Token de reset passou a ser armazenado como hash e entregue por e-mail
- Atividades saíram de um campo de texto único para tabela própria por equipe
- Datas deixaram de ser texto e viraram `DateTime`
- Migrations com Alembic — alterar o modelo não exige mais recriar o banco
- `app.py` de 1.005 linhas dividido em blueprints e serviços
- wkhtmltopdf (arquivado) substituído por WeasyPrint
- Blueprints órfãos que referenciavam campos inexistentes foram removidos
