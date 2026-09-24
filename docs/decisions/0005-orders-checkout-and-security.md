# ADR 0005: Arquitetura de Pedidos, Checkout e Recálculo Server-Side

## Data
2026-09-24

## Status
Aceito

## Contexto
O processo de submissão e gravação de pedidos é o núcleo financeiro e operacional de qualquer plataforma de delivery. É imperativo que:
1. Os preços dos produtos e adicionais nunca sejam aceitos às cegas do cliente/navegador, prevenindo ataques de manipulação de parâmetros (onde um atacante poderia tentar pagar R$ 0,01 por um hambúrguer de R$ 35,00).
2. O histórico do pedido seja imutável: se o lojista alterar o preço do lanche amanhã de R$ 30,00 para R$ 35,00, os pedidos anteriores devem manter os preços congelados nos itens (`unit_price`) e nos adicionais (`OrderItemOption.price`).
3. Todo pedido tenha um identificador público seguro (`UUID` via `public_id`) para links do cliente, mas também um número sequencial simples e legível pelo lojista e pelo motoboy (ex: `#1001`, `#1002`).
4. As formas de pagamento no MVP sejam informativas (Pix, Dinheiro com troco, Cartão na entrega) sem integração de gateway de pagamento, mas a arquitetura deve permitir plugar pagamentos online (Mercado Pago, Asaas, etc.) futuramente sem alterar a modelagem central.

## Decisão
1. **Modelagem de Pedidos**:
   - `Order`: herda de `StoreBoundedModel` e `UUIDModel`.
     - `order_number`: inteiro sequencial particionado por loja (iniciando em 1001).
     - `status`: escolhas claras (`NOVO`, `ACEITO`, `EM_PREPARACAO`, `PRONTO`, `SAIU_PARA_ENTREGA`, `CONCLUIDO`, `CANCELADO`).
     - `delivery_type`: `DELIVERY` ou `PICKUP`.
     - `payment_method`: `MONEY`, `PIX`, `DEBIT_CARD`, `CREDIT_CARD`, `MEAL_VOUCHER`, `OTHER`.
     - `change_for`: valor de troco caso a forma seja dinheiro.
     - `subtotal`, `delivery_fee`, `total`: valores monetários decimais calculados exclusivamente no backend.
     - Dados de endereço congelados no registro do pedido.
   - `OrderItem`: armazena `product_name`, `unit_price`, `quantity`, `subtotal`, `total` e `notes`.
   - `OrderItemOption`: armazena o nome e preço do adicional congelado no momento da compra.
2. **Camada de Serviço Centralizada (`OrderService`)**:
   - Executada dentro de bloco `transaction.atomic()` com lock pessimista (`select_for_update`) na loja para geração sequencial e sem colisão de `order_number`.
   - Busca produtos e opções ativas no banco de dados e recalcula subtotais e taxas de entrega.
   - Atualiza contador de pedidos e valor acumulado do cliente (`Customer.orders_count`, `Customer.total_spent`).
3. **Isolamento Estrito**:
   - O lojista autenticado só lista e atualiza pedidos pertencentes às lojas das quais é membro (`IsStoreMember`).
   - O consumidor acompanha seu pedido via UUID seguro (`/pedidos/<public_id>/`).

## Consequências
- Proteção 100% contra fraudes de alteração de preço.
- Relatórios e histórico contábil sempre consistentes.
- Preparado para a transição para WhatsApp na Fase 6 e pagamentos online em fases posteriores.
