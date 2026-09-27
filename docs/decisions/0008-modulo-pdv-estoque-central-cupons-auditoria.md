# 0008. Módulo de PDV (Ponto de Venda), Estoque Unificado Central e Cupons de Desconto

**Data:** 2026-09-25  
**Status:** Aprovado e Implementado  
**Autores:** Equipe de Engenharia MePedi  

---

## 1. Contexto & Objetivos

Para atender estabelecimentos como confeitarias, pizzarias, hamburguerias e docerias que realizam vendas presenciais no balcão e entregas online simultaneamente, foi desenvolvido o módulo de **PDV (Ponto de Venda / Balcão)** 100% integrado ao sistema **MePedi**.

### Requisitos Mandatórios
1. **Estoque Único Centralizado:** O cardápio online e o PDV DEVEM utilizar o MESMO estoque. Nenhuma divisão ou estoque separado foi criado. Quando o estoque atinge zero, o produto torna-se "Esgotado" tanto na web quanto no balcão, bloqueando vendas excedentes.
2. **Sequência Global de Pedidos:** Pedidos ONLINE e PDV compartilham a mesma numeração sequencial consecutiva (`#1001 ONLINE`, `#1002 PDV`, `#1003 ONLINE`, `#1004 PDV`).
3. **Rastreabilidade e Origem:** Todo pedido registra sua origem (`ONLINE` vs `PDV`), operador responsável e gera histórico auditável em `StockMovement`.
4. **Idempotência no Cancelamento:** O cancelamento de pedidos devolve os itens ao estoque de forma atômica e estritamente idempotente (flag `stock_returned` previne estornos duplicados).
5. **Preço Promocional e % OFF:** Permite registrar preço base e preço promocional com cálculo automático da porcentagem de desconto (`% OFF`), exibida em badges visuais no cardápio, no painel, no PDV e na nota térmica.
6. **Cupons de Desconto Promocionais:** Gestão completa no painel do lojista (porcentagem ou valor fixo, valor mínimo, limites de uso, validade, cupom público em banner vs código secreto), aplicáveis no Checkout Web e no PDV.

---

## 2. Modelagem do Banco de Dados

### 2.1 Catálogo (`apps/catalog/models.py`)
- **`Product`:**
  - `code`: Código alfanumérico ou SKU único por loja (`unique_together = ('store', 'code')`).
  - `track_stock`: Booleano para ativar/desativar controle de estoque.
  - `stock_quantity`: Quantidade inteira disponível em estoque.
  - `is_promotional`: Booleano que ativa o preço em promoção.
  - `promotional_price`: Preço promocional em R$.
  - Propriedades calculadas:
    - `current_price`: Retorna o valor promocional quando ativo, ou o preço original.
    - `discount_percent`: Calcula a porcentagem real de desconto (ex: 50 -> 35 = 30% OFF).
    - `is_in_stock`: Avalia disponibilidade imediata.
- **`StockMovement`:**
  - Registra cada variação de estoque com `store`, `product`, `order`, `movement_type` (`SALE_ONLINE`, `SALE_PDV`, `CANCEL_RETURN`, `MANUAL_ADJUST`, `RESTOCK`), `quantity`, `previous_stock`, `current_stock` e `notes`.

### 2.2 Pedidos & Cupons (`apps/orders/models.py`)
- **`Coupon`:**
  - `code`: Código do cupom em maiúsculas (ex: `BEMVINDO10`).
  - `discount_type`: `PERCENTAGE` (%) ou `FIXED` (R$).
  - `discount_value`: Valor monetário ou percentual.
  - `min_order_value`: Subtotal mínimo exigido para liberação do cupom.
  - `apply_to_delivery`: Permite abater taxa de entrega quando aplicável.
  - `max_uses`: Limite máximo de ativações do cupom.
  - `times_used`: Contador atômico de usos.
  - `valid_until`: Data e hora limite de expiração.
  - `is_public`: Exibe em banner de destaque no cardápio web.
  - `is_active`: Liga/desliga manual do cupom.
  - Métodos: `validate_for_order(subtotal, delivery_fee)` e `calculate_discount(subtotal, delivery_fee)`.
- **`Order`:**
  - `origin`: Identificador da origem (`ONLINE` vs `PDV`).
  - `operator`: Chave estrangeira para o usuário lojista/operador que efetuou a venda.
  - `discount`: Valor monetário do desconto aplicado.
  - `coupon`: Chave estrangeira para o objeto `Coupon`.
  - `coupon_code`: Snapshot do código utilizado.
  - `stock_returned`: Flag de controle booleana garantindo idempotência na devolução de estoque.

---

## 3. Serviços e Regras de Negócio

### 3.1 `StockService` (`apps/catalog/services.py`)
- `decrement_stock(product, quantity, order, movement_type)`: Utiliza `select_for_update()` para bloqueio pessimista em nível de linha no banco, impedindo condições de corrida (*race conditions*) em compras simultâneas.
- `restore_stock(order)`: Restaura atômica e idempotentemente os itens do pedido cancelado, marcando `stock_returned = True` e registrando movimentações `CANCEL_RETURN`.
- `adjust_stock(product, new_quantity, user, notes)`: Ajuste manual de balanço de estoque pelo lojista.

### 3.2 `OrderService` (`apps/orders/services.py`)
- `create_order(...)`: Criador de pedidos do cardápio online com validação de cupom, aplicação de preços promocionais e débito atômico de estoque.
- `create_pos_order(...)`: Criador exclusivo para vendas balcão do PDV com status imediato `CONCLUIDO`, vinculação do operador autenticado, débito atômico de estoque (`SALE_PDV`) e geração do mesmo sequencial global `#100X`.
- Identificação de cliente balcão com telefone numérico consistente (`f"0000{store.id:06d}"[:11]`) prevenindo colisões ou erros de chave única no banco.

---

## 4. Interfaces e Experiência do Usuário (UI/UX)

### 4.1 Ponto de Venda (`templates/dashboard/pos.html`)
- **Atalhos Rápidos:** Atalho global de teclado `F2` para fechamento rápido de vendas.
- **Busca Instantânea:** Filtro por nome ou código de barras/SKU com navegação dinâmica por pílulas de categorias.
- **Feedback de Estoque:** Badges visuais em tempo real (Verde: estoque normal, Amarelo: estoque baixo ≤ 5, Vermelho: esgotado).
- **Personalização de Sabores/Adicionais:** Modal dinâmico para produtos com grupos de complementos obrigatórios ou opcionais.
- **Formas de Pagamento:** Botões rápidos para Dinheiro (com cálculo automático de troco em tempo real), Pix, Cartão de Crédito e Débito.
- **Impressão Térmica:** Pré-visualização e impressão direta em bobina térmica padrão de **58mm** e **80mm**, com cabeçalho da loja, identificador do operador, detalhamento de itens, adicionais, descontos e troco.

### 4.2 Cardápio Público & Checkout Online
- **Banner de Cupons:** Exibição elegante no topo do cardápio digital de cupons públicos ativos com botão de cópia com um clique.
- **Destaque Promocional:** Preço original riscado, preço promocional em destaque e badge de porcentagem `% OFF`.
- **Prevenção de Carrinho:** `cart.js` impede a adição de quantidades superiores ao estoque disponível e bloqueia produtos com saldo zero.
- **Checkout Web:** Campo de cupom de desconto com validação em tempo real via endpoint REST (`/api/v1/orders/coupon/validate/`), recálculo automático do total e visualização do abatimento.

---

## 5. Auditoria de Testes Automatizados

A suíte completa de testes executada no ambiente totalizou **56 testes**, todos aprovados com 100% de sucesso:

| Módulo | Qtd de Testes | Status |
| :--- | :--- | :--- |
| `apps.orders.tests` (inclui auditoria PDV e Cupons) | 25 | **OK (100%)** |
| `apps.catalog.tests` (produtos, variações e estoque) | 7 | **OK (100%)** |
| `apps.stores.tests` (multi-tenancy, horários e configs) | 12 | **OK (100%)** |
| `apps.delivery.tests` & `apps.customers.tests` | 12 | **OK (100%)** |
| **Total Global** | **56 testes** | **100% OK** |

### Casos de Teste Chave Auditados
1. **Estoque Central Compartilhado:** Venda de 3 un online + venda de 5 un no PDV no mesmo produto debitou de 20 para 12 no estoque único centralizado.
2. **Prevenção de Sobrevenda (*Overselling*):** Tentativa de compra de 3 unidades com estoque 2 foi rejeitada com `ValidationError` tanto no fluxo online quanto no PDV balcão.
3. **Idempotência no Cancelamento:** Pedido com 4 itens cancelado restaurou o estoque exatamente uma vez. Chamadas repetidas mantiveram o saldo intacto.
4. **Sequência Global Unificada:** Pedidos alternados Online e PDV geraram numeração sequencial estritamente consecutiva (`#1001`, `#1002`, `#1003`, `#1004`).
5. **Regras de Cupons:** Testados com êxito desconto percentual, desconto fixo, barreira de pedido mínimo, expiração temporal e limite máximo de utilizações atingido.
