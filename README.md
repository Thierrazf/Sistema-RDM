# Sistema RDM — Gestão de Mudanças e Crises

> **Projeto piloto.** Versão de referência publicada para demonstração. Os dados
> de exemplo (nomes, e-mails, organização) são fictícios.

Aplicação web para registrar **Requisições de Mudança (RDM)**, planejar a janela
de execução entre as equipes de TI e comunicar a mudança por e-mail com o PDF
anexado. Substitui o fluxo manual em Word + PDF.

## Funcionalidades

- **RDM em 4 etapas**: identificação, impacto e risco, janela e plano de
  trabalho, autorização.
- **Plano de trabalho por equipe** (Infraestrutura, Front-end, Back-end, Banco de
  Dados), com ordem, responsável, duração e rollback por atividade. A duração da
  janela é calculada a partir das atividades.
- **Catálogo de atividades recorrentes**, para não redigitar o que se repete.
- **Comunicação por e-mail** com pré-visualização, destinatários sugeridos e PDF
  anexo (Microsoft Graph ou SMTP).
- **Registro de crises** com linha do tempo e comunicado.
- **Relatórios gerenciais por IA** (OpenAI, Anthropic, Gemini ou endpoint
  compatível). Só são enviados totais agregados, nunca dados pessoais.
- **Trilha de auditoria** de acesso: login, falha, bloqueio, logout e reset, com
  IP e user-agent.

## Stack

Python 3.12 · Flask · SQLAlchemy/Alembic · PostgreSQL (SQLite em
desenvolvimento) · Redis · WeasyPrint · Gunicorn · Docker

## Como rodar

### Com Docker (recomendado)

```bash
cp .env.example .env        # preencha SECRET_KEY e POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec web flask db upgrade
docker compose exec web flask criar-admin --email admin@exemplo.com.br
docker compose exec web flask carregar-catalogo
```

Acesse `http://localhost:8000`. Para desligar: `docker compose down`. Os dados
continuam salvos no volume.

> O compose sobe em modo produção, em que o cookie de sessão exige HTTPS. Em
> `localhost` funciona. Para acesso pela rede, coloque um proxy HTTPS (nginx/IIS)
> na frente da porta 8000.

### Local (desenvolvimento)

```bash
python -m venv venv
source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # Windows: copy .env.example .env

flask --app wsgi db upgrade
flask --app wsgi criar-admin --email admin@exemplo.com.br
flask --app wsgi carregar-catalogo
flask --app wsgi run --debug
```

Acesse `http://127.0.0.1:5000`. No Windows, a geração de PDF exige o
[GTK3 Runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases).

### Comandos de administração

| Comando | Função |
|---|---|
| `flask criar-admin --email <e-mail>` | Cria o primeiro administrador (pede a senha) |
| `flask carregar-catalogo` | Carrega as atividades padrão das 4 equipes |
| `flask carregar-pessoas` | Cadastra autorizadores e analistas a partir de `pessoas.csv` (modelo: `pessoas.example.csv`) |
| `flask testar-email --para <e-mail>` | Envia um e-mail de teste e mostra o erro exato |

## Configuração

Todas as variáveis estão documentadas em [`.env.example`](.env.example). As principais:

| Variável | Uso |
|---|---|
| `SECRET_KEY` | Obrigatória em produção (mín. 32 caracteres). Também cifra as chaves de IA |
| `ORG_NOME` | Nome da organização exibido no cabeçalho |
| `ALLOWED_EMAIL_DOMAINS` | Domínios de e-mail autorizados. Vazio libera qualquer domínio |
| `DATABASE_URL` | Banco de dados. Sem ela, usa SQLite local |
| `EMAIL_BACKEND` | `auto`, `graph` ou `smtp` |
| `GRAPH_*` / `SMTP_*` | Credenciais de envio de e-mail |

Dados da organização (`.env`, `pessoas.csv`, banco e PDFs) ficam fora do
repositório.

### E-mail via Microsoft Graph

Recomendado, porque a Microsoft está desativando a autenticação SMTP:

1. No Entra ID, registre um aplicativo e crie um segredo de cliente.
2. Conceda a permissão de aplicativo `Mail.Send` com consentimento do administrador.
3. Restrinja o aplicativo a uma única caixa com `New-ApplicationAccessPolicy`.
   Sem isso, ele pode enviar como qualquer usuário do tenant.
4. Preencha `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET` e
   `EMAIL_REMETENTE` no `.env`.

O segredo expira em no máximo 24 meses. Anote a data.

## Perfis de acesso

| Perfil | Permissões |
|---|---|
| **Analista** | Cria e edita as próprias RDMs, registra andamento das atividades |
| **Gestor** | Tudo do analista, mais aprovar, alterar status, enviar comunicados e excluir |
| **Administrador** | Tudo, mais usuários, catálogo, relatórios por IA e trilha de acesso |

Quem só assina ou autoriza pode ser cadastrado como **"Apenas referência"**:
aparece nos seletores, no e-mail e no PDF, mas não faz login.

## Segurança

- Senhas com hash, CSRF, rate limit e bloqueio de conta por tentativas.
- Token de redefinição de senha armazenado como hash.
- Cabeçalhos de segurança e HSTS em produção.
- Chaves de API de IA cifradas no banco.
- Bloqueio de chamadas de IA para IPs privados (proteção contra SSRF).

Antes de usar em produção: HTTPS no proxy, PostgreSQL, Redis para o rate limit,
conta de e-mail dedicada e rotina de backup do banco.

## Testes

```bash
python -m tests.teste_fluxo         # login, RDM, encerramento, permissões, usuários
python -m tests.teste_telas         # renderiza todas as telas
python -m tests.teste_seguranca     # senhas, cabeçalhos, CSRF, controle de acesso
python -m tests.teste_email         # Graph, SMTP e tratamento de falhas
python -m tests.teste_relatorio_ia  # configuração cifrada e dados agregados
python -m tests.teste_pdf           # gera um PDF de exemplo em instance/pdfs/
```

## Estrutura

```
app/
  __init__.py        factory, blueprints, comandos CLI
  config.py          configuração por ambiente
  models.py          User, RDM, Atividade, Catálogo, Crise, LogAcesso
  security.py        permissões, validações, auditoria
  blueprints/        auth, painel, rdm, crise, admin
  services/          e-mail, Graph, PDF, relatórios por IA
  templates/         telas, e-mails e PDFs
migrations/          Alembic
tests/               testes funcionais
wsgi.py              ponto de entrada
```

## Status

Piloto funcional, sem garantias de suporte. Todos os direitos reservados. O
código está disponível para consulta e não tem licença de uso, cópia ou
redistribuição.
