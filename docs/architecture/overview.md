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
- `orders`: Cabeçalho do pedido, itens, opções selecionadas, status e totais recalculados.
- `whatsapp`: Formatação de mensagens pré-preenchidas e link dinâmico para WhatsApp.
- `core`: Classes base abstratas, decorators, validações globais e utilitários.
