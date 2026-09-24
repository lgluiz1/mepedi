# Arquitetura do Sistema - IA-Pedidos

## Visão Geral
A plataforma **IA-Pedidos** é um SaaS multi-loja de cardápio digital e gestão de pedidos online, projetada para pequenos e médios comerciantes.

## Stack Tecnológica
- **Linguagem**: Python 3.12+ / 3.14
- **Framework Web**: Django 5.x + Django REST Framework (DRF)
- **Banco de Dados**: PostgreSQL (suporte a SQLite para desenvolvimento rápido/testes)
- **Containerização**: Docker e Docker Compose
- **Frontend Inicial**: Django Templates, HTML5 semântico, CSS responsivo/moderno (Vanilla CSS), JavaScript modular sem frameworks pesados. Preparado para API REST no futuro.

## Estratégia de Multi-Tenancy
- **Modelo de Isolamento**: Multi-tenancy lógico compartilhado com `store_id` (ForeignKey para `Store`) em todas as entidades que pertencem a uma loja.
- **Identificação Pública**:
  - Padrão MVP: `https://dominio.com.br/<slug-da-loja>/`
  - Futuro: Subdomínios (`https://<slug-da-loja>.dominio.com.br`)
- **Segurança Entre Lojas**:
  - Queries do painel administrativo filtram estritamente pelo `store` do usuário autenticado.
  - Endpoints de catálogo e criação de pedidos utilizam o slug da loja no path para isolar contexto.
  - Regra de ouro: A Loja A JAMAIS poderá visualizar ou modificar registros da Loja B.

## Módulos Django (Apps)
1. **`core`**:
   - Modelos base abstratos (`TimeStampedModel`, `UUIDModel`).
   - Utilitários globais, middlewares de contexto de loja, mixins e validações reutilizáveis.
2. **`accounts`**:
   - Modelo customizado de usuário (`User`).
   - Autenticação, login, logout, gerenciamento de perfil e credenciais do lojista.
   - Associação de usuários às lojas (`UserStoreRole` / `owner` / `members`).
3. **`stores`**:
   - Modelo `Store`: dados comerciais, nome, slug único, CNPJ/CPF, endereço, telefone, WhatsApp, status (aberto/fechado/pausado), horários de funcionamento (`BusinessHour`).
   - Configurações gerais da loja.
4. **`catalog`**:
   - Categorias (`Category`), Produtos (`Product`), Grupos de Opções (`OptionGroup`), Opções/Adicionais (`OptionItem`).
   - Controle de disponibilidade, preços e ordenação.
5. **`customers`**:
   - Modelo `Customer`: nome, telefone (identificador lógico principal por loja), CPF (opcional), endereços (`CustomerAddress`).
   - Histórico e dados sem exigência de senha no MVP.
6. **`orders`**:
   - Pedidos (`Order`): código amigável (`#1001`), status (`NOVO`, `ACEITO`, `EM_PREPARACAO`, `PRONTO`, `SAIU_PARA_ENTREGA`, `CONCLUIDO`, `CANCELADO`), tipo (`ENTREGA`, `RETIRADA`), subtotal, taxa de entrega, total, forma de pagamento, troco, observações.
   - Itens do Pedido (`OrderItem`) e opções selecionadas (`OrderItemOption`).
   - Recálculo forçado de valores no backend (segurança contra manipulação de preço).
7. **`delivery`**:
   - Configurações de entrega e taxas por região/bairro (`DeliveryZone`).
8. **`whatsapp`**:
   - Gerador de mensagens estruturadas para envio de pedidos via URL do WhatsApp (`https://wa.me/...`).
   - Preparado para futura transição para API oficial do WhatsApp Business.

## Infraestrutura & Deploy
- `docker-compose.yml` orquestrando serviço web (Django/Gunicorn) e banco de dados (PostgreSQL 16).
- Variáveis de ambiente gerenciadas via `.env` (com `.env.example`).
