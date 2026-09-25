# ADR 0007: Auditoria de Segurança Multi-Tenant e Validação End-to-End

## Data
2026-09-24

## Status
Aceito

## Contexto
A Fase 7 representa a consolidação final da plataforma SaaS IA-Pedidos. Antes do lançamento, é mandatório garantir que:
1. O isolamento lógico entre estabelecimentos comerciais (Multi-Tenancy) seja intransponível. A Loja A JAMAIS poderá visualizar, alterar ou excluir pedidos, catálogos, adicionais, clientes ou configurações da Loja B.
2. O ciclo de vida ponta a ponta (E2E) — desde o cadastro do lojista, publicação do cardápio, navegação móvel, cálculo server-side de frete, finalização de pedido, comanda WhatsApp e acompanhamento pelo lojista — funcione harmoniosamente sem falhas de integração.
3. Cabeçalhos de segurança (X-Frame-Options, CSRF, XSS filter, HSTS) e tratamento centralizado de exceções de validação estejam ativos e prontos para produção.

## Decisão

### 1. Auditoria e Blindagem Multi-Tenant
- **Verificação em Camadas**:
  - `IsStoreMember` em nível de permissionamento REST.
  - Injeção obrigatória do contexto da loja em serializers (`ProductSerializer.validate()`) para barrar tentativas de vinculação cruzada (ex: associar categoria da Loja A a produto da Loja B).
  - Bloqueio de acesso 403 Forbidden em todos os endpoints de pedidos, catálogo, zonas de entrega e horários quando o usuário autenticado não pertence à loja da URL.
  - Bloqueio de acesso no Painel Web (`/painel/<slug>/`) contra acessos não autorizados.

### 2. Tratamento Robusto de Validações Server-Side
- Mapeamento explícito de `django.core.exceptions.ValidationError` para respostas estruturadas HTTP 400 Bad Request nos endpoints públicos de criação de pedidos.
- Garantia de que tentativas de compras em lojas com pedidos pausados ou valores abaixo do pedido mínimo (`minimum_order_value`) sejam recusadas no ato com mensagens claras ao consumidor.

### 3. Hardening de Segurança em Produção
- Configuração de cabeçalhos de segurança em `config/settings.py` quando `DEBUG=False`:
  - `SECURE_BROWSER_XSS_FILTER = True`
  - `SECURE_CONTENT_TYPE_NOSNIFF = True`
  - `X_FRAME_OPTIONS = 'DENY'`
  - `CSRF_COOKIE_SECURE = True`
  - `SESSION_COOKIE_SECURE = True`
  - `SECURE_HSTS_SECONDS = 31536000` (1 ano) com preload e subdomínios.

### 4. Suíte de Testes End-to-End e Regressão (`apps/core/tests.py`)
- Simulação completa do fluxo:
  - Registro de 2 lojas rivais.
  - Configuração de produtos e opcionais.
  - Acesso público móvel ao cardápio SSR e API.
  - Cálculo de frete por bairro.
  - Checkout com recálculo forçado de preços no backend.
  - Geração de WhatsApp deep link oficial (`wa.me`).
  - Fluxo completo no painel do lojista com transições de status (`NOVO` ➔ `ACEITO` ➔ `EM_PREPARACAO` ➔ `PRONTO` ➔ `SAIU_PARA_ENTREGA` ➔ `CONCLUIDO`).
  - Ataques simulados de injeção cross-store bloqueados com sucesso.

## Consequências
- A plataforma atinge 100% de cobertura nos requisitos do MVP.
- Total de 59 testes automatizados cobrindo todos os módulos do sistema.
- Base de código pronta para deploy em ambiente de produção com Docker.
