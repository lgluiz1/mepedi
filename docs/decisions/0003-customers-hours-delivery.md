# ADR 0003: Gestão de Clientes sem Senha, Horários em Tempo Real e Zonas de Entrega

## Data
2026-09-24

## Status
Aceito

## Contexto
A experiência de compra no delivery precisa ser o mais rápida e sem atrito possível. Exigir que o cliente crie uma conta com senha em cada lanchonete ou restaurante reduz drasticamente a conversão de pedidos. Ao mesmo tempo, é essencial:
1. Identificar o cliente de forma confiável pelo número de telefone dentro da loja (`Customer`), recuperando seus endereços salvos (`CustomerAddress`).
2. Saber com precisão se a loja está aberta para receber pedidos no momento exato em que o cliente abre o cardápio, combinando o horário semanal (`BusinessHour`), abertura manual (`is_open`) e botão de pânico/pausa temporária (`is_paused`).
3. Suportar modalidades de Entrega e Retirada, permitindo cobrança de taxa de entrega calculada por região/bairro (`DeliveryZone`).

## Decisão
1. **Identificação do Cliente por Loja**:
   - `Customer`: Pertence estritamente a uma loja (`StoreBoundedModel`), com `unique_together = ('store', 'phone')`.
   - Normalização do telefone: apenas dígitos numéricos com DDD (ex: `11999998888`), evitando duplicidades causadas por máscaras ou espaços.
   - O consumidor não possui senha no MVP. A identificação ocorre durante o fluxo de checkout ao informar o telefone.
2. **Cálculo de Status Aberto/Fechado em Tempo Real**:
   - Método `Store.is_currently_open()`:
     - Se `is_active` for `False`, retorna `False`.
     - Se `is_paused` for `True` (pedidos pausados manualmente pelo lojista), retorna `False`.
     - Se `is_open` manual for `True`, a loja é considerada aberta imediatamente.
     - Caso contrário, consulta o dia da semana atual e o horário no fuso da loja (`America/Sao_Paulo`). Se houver um registro de `BusinessHour` ativo onde `opening_time <= agora <= closing_time`, retorna `True`.
3. **Zonas e Taxas de Entrega**:
   - `DeliveryZone`: `(StoreBoundedModel)` - Define o nome da zona, bairros atendidos, taxa fixa de entrega (`DecimalField`), prazo estimado e status ativo.
   - O cálculo do frete é centralizado no backend, evitando que o frontend envie taxas arbitrárias.

## Consequências
- Alta conversão para os clientes finais da loja.
- Cada lojista é dono da sua própria base de clientes (`Customer`), sem vazamento de histórico para outros concorrentes da plataforma SaaS.
- Flexibilidade operacional para o lojista abrir, pausar e definir taxas de entrega claras.
