# ADR 0006: Integração com WhatsApp e Painel de Pedidos em Tempo Real

## Data
2026-09-24

## Status
Aceito

## Contexto
Na Fase 6, a plataforma necessita de:
1. Um canal de comunicação direto, sem fricção e de alta conversão para confirmar pedidos: o **WhatsApp**. O envio estruturado dos detalhes do pedido para o WhatsApp do estabelecimento comercial permite que o comerciante receba instantaneamente a comanda formatada, enquanto o link público seguro permite que o cliente acompanhe o status em tempo real.
2. Um **Painel do Lojista (Merchant Dashboard)** web ágil, moderno e responsivo, onde o lojista e seus atendentes possam gerenciar o fluxo operacional dos pedidos (Novos, Aceitos, Preparo, Prontos, Entrega, Concluídos) com atualizações em 1 clique, alertas sonoros sintetizados para novos pedidos e alternância rápida do status da loja (aberta/pausada/fechada).

## Decisão

### 1. Formatação e Deep Linking do WhatsApp (`apps/whatsapp`)
- **Sanitização de Telefone**: O serviço `clean_phone_number` extrai apenas dígitos e normaliza telefones brasileiros garantindo o código do país `55` (ex: `(11) 98765-4321` -> `5511987654321`).
- **Mensagem Estruturada**: `format_order_whatsapp_message` gera uma mensagem com hierarquia visual rica (emojis, separadores, cabeçalho de pedido com número amigável `#1001`, dados do cliente, modalidade Entrega/Retirada, endereço completo com ponto de referência, itens com adicionais (+) e remoções (-), subtotal, frete, valor total, forma de pagamento, troco calculado e link público para rastreamento em tempo real).
- **Link Oficial `wa.me`**: `build_whatsapp_link` codifica a mensagem com `urllib.parse.quote` e monta a URL oficial `https://wa.me/{phone}?text={encoded_message}`.
- **Deep Link de Redirecionamento 302**: Rota `GET /<store_slug>/pedidos/<public_id>/whatsapp/` e botão de destaque na tela de status do pedido (`order_detail.html`), permitindo envio em 1 clique tanto no mobile quanto no desktop.
- **Comunicação Reversa Lojista ➔ Cliente**: O painel do lojista gera links rápidos para o comerciante iniciar conversa no WhatsApp do cliente com 1 clique (`get_customer_whatsapp_link`).

### 2. Painel do Lojista (`dashboard_views.py` e `templates/dashboard/`)
- **Autenticação e Multi-Tenancy**:
  - Acesso protegido por sessão e decorador `@login_required(login_url='/painel/login/')`.
  - O painel filtra estritamente as lojas vinculadas ao usuário autenticado (`StoreMembership`), impedindo que o Lojista A acerte pedidos da Loja B (HTTP 403 Forbidden).
  - Suporte a multi-lojas: caso o lojista possua mais de uma loja, um seletor no topo alterna entre as operações.
- **Métricas e Abas de Status**:
  - Contadores de pedidos e faturamento do dia em tempo real.
  - Abas interativas com badge com contador por status (`NOVO`, `ACEITO`, `EM_PREPARACAO`, `PRONTO`, `SAIU_PARA_ENTREGA`, `CONCLUIDO`, `CANCELADO`).
- **Ações em 1 Clique com Atualizações AJAX**:
  - Transição de status rápida sem recarregar a tela (`PATCH /api/v1/orders/merchant/{store_id}/{id}/status/`).
  - Botão de controle operacional rápido da loja (pausar novos pedidos / retomar pedidos) via `PATCH /api/v1/stores/merchant/{store_id}/toggle-status/`.
- **Motor em Tempo Real e Som Sintetizado (Zero Dependência Externa)**:
  - Polling a cada 8 segundos que detecta novos pedidos e atualiza status.
  - Alerta sonoro sintetizado em tempo real utilizando a **Web Audio API** nativa dos navegadores (acorde duplo de sino Ding-Dong D5/A5), eliminando arquivos externos de áudio que poderiam falhar por 404 ou latência de rede.
  - Notificação flutuante (Toast) animada informando a chegada de novos pedidos.

## Consequências
- Aumento drástico na agilidade do lojista para aceitar e despachar pedidos.
- Zero atrito para o cliente no envio de comprovantes e comanda pelo WhatsApp.
- Arquitetura 100% pronta para a Fase 7 (testes de ponta a ponta, segurança e refinamento geral).
