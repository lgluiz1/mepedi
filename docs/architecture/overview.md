# Visão Geral da Arquitetura

## Modelo de Dados e Multi-Tenancy

O IA-Pedidos foi projetado desde o dia zero para atender múltiplas lojas em uma infraestrutura compartilhada (Shared Database, Shared Schema com isolamento lógico via chave estrangeira `store_id`).

### Princípios de Design
1. **Isolamento de Loja (Tenancy)**:
   - Toda entidade privada (categorias, produtos, pedidos, clientes, zonas de entrega, etc.) possui obrigatoriamente um relacionamento com `Store`.
   - Views autenticadas no painel do lojista injetam um filtro implícito para a loja do usuário autenticado.
   - Acesso público a cardápios é resolvido exclusivamente pelo `slug` da loja na URL: `/{store_slug}/`.
2. **Resiliência e Escalabilidade**:
   - Modelos base herdam de `TimeStampedModel` com `created_at` e `updated_at`.
   - IDs primários com inteiros auto-incrementais ou UUID para segurança pública em pedidos.
   - Índices em colunas frequentemente consultadas: `slug` em `Store`, `phone` + `store_id` em `Customer`, `status` em `Order`.
3. **Cálculo de Preço Centralizado**:
   - Nunca aceitar valores calculados enviados pelo cliente via JavaScript.
   - O backend sempre busca o preço unitário atual do produto e das opções no banco de dados e calcula:
     `total = sum(item.price + options.price) + delivery_fee`.

### Divisão de Aplicativos Django
- `accounts`: Usuários, perfis, autenticação de lojistas e permissões.
- `stores`:
  - `Store`: Cadastro da loja, endereço comercial, slug público único, modalidades de atendimento (`allows_delivery`, `allows_pickup`).
  - `BusinessHour`: Horários de funcionamento semanais.
  - Cálculo de disponibilidade em tempo real: método `is_currently_open()` que combina status ativo, botão de pausa de pedidos (`is_paused`), abertura manual (`is_open`) e a grade semanal no fuso local.
  - Interface pública do cardápio: rota `/<slug:store_slug>/` renderizando SSR responsivo mobile-first com `templates/stores/public_menu.html`, `static/css/menu.css` e carrinho interativo em `static/js/cart.js`.
  - Persistência de carrinho: `localStorage` isolado por slug da loja (`ia_cart_{store_slug}`).
- `catalog`:
  - `Category`: Categorias por loja com ordenação personalizada e status ativo.
  - `Product`: Produtos com foto, descrição, preço decimal e validação de loja cruzada contra a categoria.
  - `OptionGroup`: Grupos de opções (adicionais pagos, remoções sem custo, escolhas obrigatórias com limites min/max).
  - `OptionItem`: Itens individuais com controle de disponibilidade de estoque e precificação adicional.
  - Endpoint público agregado `GET /api/v1/catalog/public/{slug}/menu/` com `prefetch_related` para entrega otimizada de cardápio ao cliente móvel.
- `customers`:
  - `Customer`: Cliente sem senha identificado pelo telefone limpo dentro da loja (`unique_together = ('store', 'phone')`).
  - `CustomerAddress`: Múltiplos endereços salvos com ponto de referência e flag de padrão.
  - Endpoint de checkout rápido: `POST /api/v1/customers/public/{slug}/identify/` que recupera dados existentes ou cria novo cliente sem fricção.
- `delivery`:
  - `DeliveryZone`: Regiões de entrega com taxa fixa, prazo estimado e lista de bairros atendidos.
  - Cálculo server-side de frete: `POST /api/v1/delivery/public/{slug}/calculate-fee/`.
- `orders`:
  - `Order`: Cabeçalho do pedido herdando de `UUIDModel` para URL pública opaca e segura (`public_id`), numeração sequencial humana por loja (`#1001`, `#1002`) controlada com bloqueio pessimista (`select_for_update`), endereço e dados de entrega congelados no momento da compra, modalidade (`delivery`, `pickup`), forma de pagamento informativa (`pix`, `cash` com `change_for`, `credit_card`, `debit_card`) e rastreamento de status (`received`, `confirmed`, `preparing`, `out_for_delivery`, `ready_for_pickup`, `delivered`, `cancelled`).
  - `OrderItem` e `OrderItemOption`: Snapshot completo e congelado de nomes e preços unitários no instante da transação, blindando o histórico contra alterações posteriores no catálogo.
  - `OrderService.create_order`: Motor transacional que valida loja aberta, aplica regra de pedido mínimo (`min_order_value`), recalcula 100% dos valores no backend e aloca numeração atômica.
  - Rotas públicas do cliente: `/<slug:store_slug>/checkout/` e `/<slug:store_slug>/pedidos/<uuid:public_id>/`.
  - APIs REST: `POST /api/v1/orders/public/{slug}/` (criação), `GET /api/v1/orders/public/{slug}/{public_id}/` (acompanhamento), `GET /api/v1/orders/merchant/` e `PATCH /api/v1/orders/merchant/{public_id}/status/` (gestão do lojista).
  - Painel Web do Lojista: `/painel/` e `/painel/<slug:store_slug>/` com gestão em tempo real, métricas diárias, kanban por status, alternância rápida de abertura/pausa e alertas sonoros com Web Audio API.
- `whatsapp`:
  - `clean_phone_number`: Sanitização de números e adição do DDI `55`.
  - `format_order_whatsapp_message`: Formatação estruturada do pedido contendo itens, adicionais, modalidade, pagamento, troco e link público de acompanhamento.
  - Deep linking e redirecionamento 302 direto para `https://wa.me/{phone}?text={quote(msg)}` via `/<slug:store_slug>/pedidos/<uuid:public_id>/whatsapp/`.
  - Links bidirecionais: cliente para loja e loja para cliente (`get_customer_whatsapp_link`).
- `core`: Classes base abstratas, decorators, validações globais e utilitários.
