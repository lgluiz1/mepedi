# Diretrizes da API REST - IA-Pedidos

## Visão Geral
O sistema adota Django REST Framework (DRF) para expor endpoints RESTful preparados para futuras integrações, aplicativos mobile ou frontends desacoplados.

## Convenções de Endpoints
- Prefixos versionados: `/api/v1/`
- Rotas públicas da loja:
  - `GET /api/v1/stores/{store_slug}/`: Dados públicos da loja e status aberto/fechado.
  - `GET /api/v1/stores/{store_slug}/menu/`: Cardápio completo com categorias, produtos e adicionais.
  - `POST /api/v1/stores/{store_slug}/orders/`: Criação de novo pedido pelo cliente final.
- Rotas autenticadas do lojista:
  - `GET /api/v1/merchant/store/`: Dados da loja do usuário autenticado.
  - `GET /api/v1/merchant/orders/`: Listagem e gerenciamento de pedidos da loja.
  - `PATCH /api/v1/merchant/orders/{id}/status/`: Atualização de status do pedido.

## Segurança e Permissões
- Todas as rotas autenticadas exigem verificação de vínculo do usuário com a loja correspondente (`IsStoreMember` / `IsStoreOwner`).
- Rate limiting aplicado a criação de pedidos para prevenir spam e abuso.
