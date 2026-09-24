# Backlog e Rastreamento de Tarefas - IA-Pedidos

## Visão Geral das Fases

- [x] **Fase 1: Fundação** *(CONCLUÍDO)*
  - [x] Definição de documentação de contexto (.agent/ e docs/)
  - [x] Configuração do ambiente (requirements.txt, Dockerfile, docker-compose.yml, .env.example)
  - [x] Inicialização do projeto Django (`config`) e apps principais
  - [x] Configuração de banco de dados (PostgreSQL + suporte a SQLite de fallback/testes)
  - [x] Criação do app `core` (modelos base, utils, mixins)
  - [x] Criação do app `accounts` (User customizado, autenticação)
  - [x] Criação do app `stores` (Store, relacionamento usuário-loja, slug único)
  - [x] Registro dos apps preliminares (`catalog`, `customers`, `orders`, `delivery`, `whatsapp`)
  - [x] Testes iniciais da Fase 1 (User, Store, vínculo usuário-loja, isolamento)
  - [x] Validação completa das migrações e suíte de testes

- [x] **Fase 2: Catálogo e Produtos** *(CONCLUÍDO)*
  - [x] Modelos de Categoria e Produto
  - [x] Grupos de opções, adicionais e remoção de ingredientes
  - [x] Painel do lojista / APIs de gestão do cardápio
  - [x] Endpoint público de cardápio da loja
  - [x] Django Admin integrado para catálogo
  - [x] Testes unitários e de isolamento do catálogo

- [x] **Fase 3: Clientes, Horários e Entrega** *(CONCLUÍDO)*
  - [x] Modelos de Customer e CustomerAddress (identificador por telefone)
  - [x] Lógica dinâmica de verificação de loja aberta/fechada/pausada
  - [x] Gestão de horários de funcionamento (BusinessHour)
  - [x] Configuração de zonas e taxas de entrega (DeliveryZone)
  - [x] Django Admin integrado para clientes e entregas
  - [x] Testes unitários e de isolamento da Fase 3

- [x] **Fase 4: Cardápio Público Mobile-First e Carrinho** *(CONCLUÍDO)*
  - [x] Rota pública de primeiro nível `/<slug:store_slug>/`
  - [x] View otimizada com pré-carregamento de categorias, produtos e opções
  - [x] Design System do cardápio mobile-first (CSS responsivo, dark theme, badges)
  - [x] Modal de produto com adicionais, remoções, regras min/max e observações
  - [x] Carrinho reativo com persistência em localStorage e drawer flutuante
  - [x] Testes automatizados da visualização pública do cardápio

- [x] **Fase 5: Checkout e Pedidos** *(CONCLUÍDO)*
  - [x] Modelos de Order, OrderItem e OrderItemOption com congelamento de preços
  - [x] Motor server-side de recálculo de preços e validação contra manipulação
  - [x] Numeração sequencial amigável de pedido por loja (#1001, #1002)
  - [x] Fluxo de checkout com identificação por telefone e modalidades entrega/retirada
  - [x] Formas de pagamento informativas (Pix, Dinheiro com troco, Cartões)
  - [x] APIs do lojista para gestão e atualização de status dos pedidos
  - [x] Templates de checkout e acompanhamento do pedido pelo cliente
  - [x] Testes unitários e de integração de pedidos e isolamento multi-loja

- [ ] **Fase 6: Integração WhatsApp e Painel de Pedidos** *(PLANEJADO)*
  - [ ] Gerador de mensagem formatada para WhatsApp
  - [ ] Redirecionamento `wa.me`
  - [ ] Painel do lojista: listagem e atualização de status dos pedidos em tempo real

- [ ] **Fase 7: Refinamento, Segurança e Testes End-to-End** *(PLANEJADO)*
  - [ ] Auditoria de segurança e isolamento multi-loja
  - [ ] Testes de carga e regressão
