# ADR 0009: Checkpoint de Implementação SaaS MePedi (Fases 8 a 14) e Plano de Retomada

**Data:** 27 de Setembro de 2026  
**Status:** Aprovado e Salvo  
**Contexto:** Ponto de restauração e persistência de progresso para prevenção contra perda de dados em caso de reinicialização ou desligamento da máquina.

---

## 1. Resumo do Progresso Concluído (Fases 1 a 14)

Concluímos **14 das 22 fases** planejadas para o SaaS MePedi, com **108 testes automatizados executados e 100% aprovados** (0 erros, 0 falhas).

### Fases Concluídas:
1. **Fases 1 a 7 (Auditoria e Arquitetura):** Mapeamento do domínio multi-tenant, modelos de loja, pedidos, clientes, produtos e faturamento.
2. **Fase 8 (Models e Migrations):** App `apps/subscriptions` criado de forma desacoplada com models:
   - `Feature`: Código único indexado e controle ativo/inativo.
   - `Plan`: Planos comerciais pagos (`Start`, `Pro`, `Gestão`). **Regra absoluta:** Planos comerciais pagos NÃO possuem limite de pedidos ou faturamento.
   - `Subscription`: Controle de ciclo de vida da loja (`TRIAL`, `ACTIVE`, `PAST_DUE`, `SUSPENDED`, `CANCELLED`, `EXPIRED`). Constraint de unicidade por loja ativa.
   - `PaymentGatewayConfig`: Configuração segura de gateways (Mercado Pago, Sandbox/Produção).
   - `PaymentHistory`: Histórico financeiro de faturas e comprovantes.
   - `WebhookEvent`: Idempotência estrita por `(gateway, external_id)`.
3. **Fase 9 (Services):**
   - `TrialService`: Cálculo em tempo real dos limites de teste (30 dias, 300 pedidos válidos, R$ 2.000 em vendas válidas). Pedidos cancelados (`Order.STATUS_CANCELLED = 'CANCELADO'`) são desconsiderados.
   - `FeatureService`: Controle centralizado de permissões (`can_access_feature`).
   - `SubscriptionService`: Gestão atômica de início de trial, ativação de planos comerciais e cancelamento.
   - `PaymentService`: Orquestração de checkout e processamento de webhooks idempotentes.
4. **Fase 10 (Permissões, Decorators e Contexto SaaS):**
   - `@feature_required(feature_code)`: Proteção de views com bloqueio JSON 403 para AJAX e tela `feature_locked.html` para navegador.
   - `subscription_context`: Context processor global injetando métricas do trial e plano ativo nos templates do painel.
   - `Store` post_save signal: Inicialização automática de Trial de 30 dias para toda nova loja.
5. **Fase 11 (Trial UI e Monitoramento):**
   - Banner superior informativo `saas_banner.html` nos painéis com métricas em tempo real e botão de contratação de planos ilimitados.
   - Hero card na tela do lojista com 3 barras de progresso visual (dias, pedidos e receita).
6. **Fase 12 (Planos Comerciais e Tela "Minha Assinatura"):**
   - Rota `/painel/<slug>/assinatura/` com vitrine comparativa dos planos Start (R$ 49,90), Pro (R$ 99,90) e Gestão (R$ 199,90).
   - Tabela de histórico de faturas e FAQ com perguntas frequentes.
   - Navegação integrada com a nova aba `💎 Minha Assinatura` em todas as telas do painel.
7. **Fase 13 (Integração Gateway Mercado Pago):**
   - `MercadoPagoGateway`: Implementação REST nativa com `urllib.request` (sem dependências externas pesadas). Geração de preferência de checkout com `back_urls`, dados do lojista e identificador seguro `external_reference`.
   - Rota de checkout `POST /painel/<slug>/assinatura/checkout/<plan_slug>/` com suporte a redirecionamento padrão e respostas JSON AJAX.
8. **Fase 14 (Webhooks e Confirmação de Retorno):**
   - Rota de retorno `/painel/<slug>/assinatura/retorno/` tratando retornos do gateway (`success`, `pending`, `failure`).
   - Endpoint receptor de webhooks `POST /api/v1/subscriptions/webhook/<gateway>/` com deduplicação de eventos via banco de dados e ativação automática do plano.

---

## 2. Ponto Exato de Retomada Amanhã

Na próxima sessão, iniciaremos a partir da **Fase 15**:

### **Fase 15 — Painel Administrativo Proprietário MePedi**
* **Objetivo:** Criar o painel administrativo de gestão central do SaaS MePedi (`administracao.mepedi.com.br` / `/gestao-saas/`), sem utilizar o Django Admin como interface principal.
* **Componentes a Implementar:**
  1. **Dashboard Geral:** Visão consolidada de todas as lojas, lojistas, planos ativos, lojas em trial e faturamento do SaaS.
  2. **Gestão de Lojistas & Lojas:** Tabela completa com filtros por status (`Trial`, `Ativo`, `Vencido`, `Cancelado`), pesquisa por nome, email, telefone, CPF/CNPJ.
  3. **Detalhes da Loja (Visão 360°):** Informações cadastrais, plano atual, histórico de upgrades/downgrades, faturas, consumo de recursos e dados operacionais.
  4. **Configuração de Gateways:** Tela administrativa para gerenciar credenciais do Mercado Pago (Access Token, Public Key, Webhook Secret) com botão "Testar Conexão".

### Fases Subsequentes no Roadmap:
* **Fase 16:** Módulo Financeiro Administrativo (MRR, receitas, gráficos de crescimento, controle de inadimplência).
* **Fase 17:** Trilha de Auditoria administrativa de ações sensíveis.
* **Fase 18:** Recurso **Modo Suporte** ("Acessar como Loja" para atendimento com log de auditoria).
* **Fases 19 a 22:** Testes automatizados do painel administrativo, suíte completa de ponta a ponta e homologação final da entrega.

---

## 3. Estado dos Containers e Ambiente

* **Docker:**
  - `ia_pedidos_web`: Porta 8000 (Daphne / Django 5.1).
  - `ia_pedidos_db`: Porta 5432 (PostgreSQL 16, volume persistido).
* **Comando para reiniciar o ambiente se necessário:**
  ```bash
  docker compose up -d
  ```
* **Comando para rodar a suíte completa de testes:**
  ```bash
  docker exec ia_pedidos_web python manage.py test accounts stores catalog customers delivery orders whatsapp analytics subscriptions
  ```
