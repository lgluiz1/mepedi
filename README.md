# MePedi - Plataforma SaaS de Cardápio Digital, Pedidos e Mesas

O **MePedi** é uma plataforma completa e moderna voltada para estabelecimentos gastronômicos (pizzarias, restaurantes, hamburguerias, bares e lanchonetes). Ele oferece cardápio digital responsivo com visual mobile-first, gestão de pedidos online para entrega e retirada, sistema integrado de mesas e comandas digitais com autenticação por QR Code e PIN de 4 dígitos, ponto de venda (PDV / Balcão) para operações presenciais e painel administrativo SaaS para gestão de planos e assinaturas.

---

## 🛠️ Tecnologias Utilizadas

- **Linguagem**: Python 3.12
- **Framework Web**: Django 5.1 & Django REST Framework
- **Servidor em Tempo Real / WebSockets**: Django Channels & Daphne (ASGI)
- **Banco de Dados**: PostgreSQL 16 (produção via rede externa Docker) / SQLite3 (fallback de testes)
- **Containers & Orquestração**: Docker & Docker Compose / Portainer Stacks
- **Front-end**: HTML5 semântico, Vanilla CSS customizado (mobile-first), JavaScript Vanilla reativo (Fetch API e WebSockets)

---

## 📋 Requisitos Pré-requisitos

### Ambiente Local (Desenvolvimento)
- Docker Desktop e Docker Compose instalados no sistema operacional.
- Git instalado.

### Ambiente de Produção (VPS Docker / Portainer)
- Docker Engine e Docker Compose (V2) instalados na VPS.
- **Portainer** instalado e configurado.
- Rede Docker externa: `database_net`.
- Container PostgreSQL central em execução, nomeado exatamente como `postgres`, conectado à rede `database_net`.
- Banco de dados e usuário criados no PostgreSQL central (ex: banco `mepedi`, usuário `mepedi`).

---

## 🚀 Como Executar Localmente (Desenvolvimento & Testes)

No ambiente local de desenvolvimento, o MePedi utiliza o arquivo `docker-compose.dev.yml`, que inclui um container isolado do PostgreSQL (`ia_pedidos_db`) e volume de código compartilhado (`.:/app`) para atualização automática sem reconstrução da imagem.

### 1. Iniciar o ambiente local
```bash
docker compose -f docker-compose.dev.yml up -d --build
```

### 2. Acompanhar os logs
```bash
docker compose -f docker-compose.dev.yml logs -f web
```

### 3. Executar migrações do banco de dados (se necessário)
```bash
docker compose -f docker-compose.dev.yml exec web python manage.py migrate
```

### 4. Executar os testes automatizados
```bash
docker compose -f docker-compose.dev.yml exec web python manage.py test --keepdb
```

### 5. Parar o ambiente local
```bash
docker compose -f docker-compose.dev.yml down
```

O sistema estará acessível localmente em `http://127.0.0.1:8000`.

---

## ⚙️ Configuração de Variáveis de Ambiente (`.env`)

Copie o modelo de variáveis de ambiente:
```bash
cp .env.example .env
```

### Variáveis Utilizadas pelo Projeto:

| Variável | Descrição | Exemplo em Produção | Exemplo Local |
| :--- | :--- | :--- | :--- |
| `DEBUG` | Ativa/desativa o modo de depuração | `False` | `True` |
| `SECRET_KEY` | Chave criptográfica única do Django | `chave-secreta-complexa-producao` | `django-insecure-mvp...` |
| `ALLOWED_HOSTS` | Hosts/domínios autorizados a acessar a aplicação | `mepedi.seudominio.com.br,127.0.0.1` | `*` |
| `DATABASE_URL` | String de conexão completa com o PostgreSQL | `postgresql://mepedi:SENHA@postgres:5432/mepedi` | `postgres://postgres:postgres@db:5432/ia_pedidos` |
| `SECURE_HSTS_SECONDS` | Tempo de cache do cabeçalho HSTS (opcional) | `31536000` | Não obrigatório |

> [!IMPORTANT]
> **Nunca comite o arquivo `.env` no Git.** As credenciais reais de produção devem ser preenchidas diretamente na interface do Portainer ao criar a Stack.

---

## 🌐 Configuração da Rede e Banco de Dados Externo na VPS

Na VPS de produção, o MePedi **não** cria outro container de PostgreSQL. Ele se integra à infraestrutura central já existente:

1. **Rede Docker Externa**:
   ```bash
   # Certifique-se de que a rede database_net existe na VPS:
   docker network inspect database_net || docker network create database_net
   ```

2. **Container Central PostgreSQL**:
   - Nome do container: `postgres`
   - Conectado à rede: `database_net`
   - Porta interna: `5432` (não precisa ser publicada para o mundo exterior)

3. **Criação do Banco de Dados no PostgreSQL Central**:
   Dentro do container `postgres` na VPS:
   ```sql
   CREATE DATABASE mepedi;
   CREATE USER mepedi WITH ENCRYPTED PASSWORD 'sua_senha_segura';
   GRANT ALL PRIVILEGES ON DATABASE mepedi TO mepedi;
   ```

---

## 🚢 Como Fazer Deploy pelo Portainer (Git Repository)

O arquivo `docker-compose.yml` na raiz do projeto está pré-configurado para implantação direta via Portainer Stacks.

1. Acesse seu painel do **Portainer**.
2. Navegue até **Stacks** &rarr; clique em **Add stack**.
3. Selecione o método de build: **Repository**.
4. Preencha as configurações do repositório:
   - **Repository URL**: `https://github.com/lgluiz1/mepedi.git`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `docker-compose.yml`
5. Na seção **Environment variables**, adicione as seguintes variáveis:
   ```env
   DEBUG=False
   SECRET_KEY=gere-uma-chave-longa-e-aleatoria-aqui
   ALLOWED_HOSTS=*
   DATABASE_URL=postgresql://mepedi:SUA_SENHA_AQUI@postgres:5432/mepedi
   ```
6. Clique no botão **Deploy the stack**.

O Portainer fará o clone do repositório Git, construirá a imagem Docker usando o [Dockerfile](file:///c:/Users/Luiz/Desktop/IA-Pedidos/Dockerfile), conectará o container `mepedi_web` à rede externa `database_net` e iniciará o Django ouvindo na porta `8000:8000`.

---

## 🔌 Portas e Redes Utilizadas

- **Porta Exposta**: `8000:8000` (permite testes na VPS e encaminhamento pelo proxy reverso).
- **Redes Docker Utilizadas**:
  - `database_net` (`external: true`): Conexão direta ao container central PostgreSQL (`postgres`).
  - `proxy_net` (`external: true`): Conexão com o Nginx Proxy Manager (`npm`).
- **Volume Persistente de Produção**: `mepedi_media` montado em `/app/media` (garante que logotipos de lojas e fotos de produtos enviados pelos lojistas sejam preservados entre deploys e reinicializações).

---

## 🛡️ Configuração do Nginx Proxy Manager (NPM)

Para disponibilizar o MePedi através do domínio **`mepedi.com.br`**, crie um novo **Proxy Host** no painel do NPM com os seguintes parâmetros:

- **Domain Names**: `mepedi.com.br`, `www.mepedi.com.br`
- **Scheme**: `http`
- **Forward Hostname / IP**: `mepedi_web`
- **Forward Port**: `8000`
- **Websockets Support**: `enabled` *(fundamental para Django Channels / Daphne)*
- **Block Common Exploits**: `enabled`
- **SSL**: Certificado Let's Encrypt gerado pelo próprio NPM com *Force SSL* ativado.

---

## 🔒 Segurança e Boas Práticas

- Arquivos `.env`, `.pem`, `.key`, `db.sqlite3`, `media/` e `staticfiles/` estão estritamente ignorados pelo `.gitignore` e `.dockerignore`.
- O código da aplicação é embutido na imagem final do Docker em produção, garantindo reprodutibilidade e conformidade de versão.
- Todas as rotas autenticadas do painel do lojista e do SaaS administrativo contam com proteção CSRF e validação de permissões de loja.
