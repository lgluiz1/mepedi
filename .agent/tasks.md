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

- [ ] **Fase 2: Catálogo e Produtos** *(PLANEJADO)*
  - [ ] Modelos de Categoria e Produto
  - [ ] Grupos de opções, adicionais e remoção de ingredientes
  - [ ] Painel do lojista: gestão do cardápio
  - [ ] Testes unitários do catálogo

- [ ] **Fase 3: Clientes, Horários e Entrega** *(PLANEJADO)*
  - [ ] Modelos de Customer e CustomerAddress (identificador por telefone)
  - [ ] Configuração de horários de funcionamento e abertura/fechamento
  - [ ] Configuração de zonas e taxas de entrega (DeliveryZone)

- [ ] **Fase 4: Cardápio Público Mobile-First e Carrinho** *(PLANEJADO)*
  - [ ] Página pública `/loja-slug/` responsiva e moderna
  - [ ] Visualização de produtos, fotos, status aberto/fechado
  - [ ] Carrinho interativo com seleção de adicionais e observações

- [ ] **Fase 5: Checkout e Pedidos** *(PLANEJADO)*
  - [ ] Fluxo de checkout com identificação por telefone
  - [ ] Recálculo obrigatório e validação server-side
  - [ ] Escolha de entrega/retirada e forma de pagamento (sem processamento financeiro no MVP)
  - [ ] Criação do pedido com numeração amigável

- [ ] **Fase 6: Integração WhatsApp e Painel de Pedidos** *(PLANEJADO)*
  - [ ] Gerador de mensagem formatada para WhatsApp
  - [ ] Redirecionamento `wa.me`
  - [ ] Painel do lojista: listagem e atualização de status dos pedidos em tempo real

- [ ] **Fase 7: Refinamento, Segurança e Testes End-to-End** *(PLANEJADO)*
  - [ ] Auditoria de segurança e isolamento multi-loja
  - [ ] Testes de carga e regressão
