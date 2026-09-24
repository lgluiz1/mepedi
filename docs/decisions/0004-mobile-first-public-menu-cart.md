# ADR 0004: Interface Pública Mobile-First do Cardápio e Arquitetura do Carrinho

## Data
2026-09-24

## Status
Aceito

## Contexto
O consumidor que acessa o link do cardápio digital (`https://dominio.com.br/loja-do-luiz`) o faz, em mais de 90% dos casos, pelo celular através do link da bio do Instagram ou encaminhado via WhatsApp. A página precisa carregar instantaneamente, apresentar visualmente o estabelecimento com alto valor percebido, exibir o status da loja com clareza imediata (Aberto / Fechado / Pausado) e oferecer uma experiência tátil de adicionar produtos, selecionar adicionais/remoções e navegar pelo carrinho sem recarregar a tela.

## Decisão
1. **Renderização Híbrida (SSR + Enriquecimento Progressivo em Vanilla JS)**:
   - Utilização de Django Templates para renderização do esqueleto e produtos no servidor. Isso garante carregamento instantâneo, compatibilidade com SEO, prévias no WhatsApp e sem flash de conteúdo em branco.
   - Um script modular JavaScript (`cart.js`) gerencia o estado do carrinho no cliente e as interações do modal de opções, sem necessidade de carregar bibliotecas externas pesadas (React, Vue, etc.).
2. **Armazenamento e Isolamento do Carrinho no Cliente**:
   - O carrinho é persistido no `localStorage` do navegador utilizando uma chave com namespace por loja: `ia_cart_{store_slug}`.
   - Isso impede que itens adicionados na Loja A apareçam no carrinho da Loja B caso o mesmo cliente acesse ambos os links no mesmo celular.
   - O carrinho sobrevive a atualizações de página e fechamento acidental da aba.
3. **Seleção de Opções com Validações em Tempo Real**:
   - O modal de produto renderiza os grupos de opções dinamicamente.
   - Regras de `min_options` e `max_options` são validadas antes de permitir o clique em "Adicionar ao Carrinho".
   - O subtotal dinâmico é atualizado em tempo real à medida que o cliente marca ou desmarca adicionais.
4. **URL de Primeiro Nível para a Loja**:
   - Configurado roteamento de primeiro nível `/<slug:store_slug>/` com resolução estrita para lojas ativas, reservando rotas administrativas com prefixo (`admin/`, `api/`).

## Consequências
- Experiência nativa ultra rápida para o cliente em smartphones.
- Zero dependências de CDN ou builds complexos de frontend no MVP.
- O backend continua sendo a autoridade de validação final no momento de submissão do pedido (Fase 5).
