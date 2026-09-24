# Requisitos de Negócio - IA-Pedidos

## 1. Visão Geral
Plataforma SaaS que permite a lojistas e comerciantes locais criarem seus próprios cardápios digitais e receberem pedidos via internet de forma simplificada, enviando os dados consolidados para o WhatsApp da loja e painel administrativo.

## 2. Personas e Perfis

### 2.1 Lojista / Administrador
- Cadastra sua loja com nome, telefone, WhatsApp, endereço e documento (CPF/CNPJ).
- Define seus horários de atendimento por dia da semana e status manual de abertura.
- Configura categorias e produtos do cardápio, com adicionais e ingredientes removíveis.
- Define taxas e regiões de entrega ou opção exclusiva de retirada.
- Acompanha pedidos em tempo real no painel administrativo e atualiza seus status.

### 2.2 Consumidor Final (Cliente)
- Acessa o cardápio público pelo link `/{slug-da-loja}/`.
- Navega pelos produtos categorizados e adiciona ao carrinho com observações e adicionais.
- Faz o checkout sem necessidade de criar conta ou senha:
  - Informa apenas telefone (chave de busca) e nome.
  - Se já comprou na loja anteriormente, seus dados/endereços recentes são pré-carregados para confirmação.
- Escolhe Entrega ou Retirada.
- Escolhe forma de pagamento informativa (Dinheiro com troco, Pix, Cartão de Crédito/Débito, etc.).
- Ao finalizar, o pedido é registrado na loja e o cliente é encaminhado ao WhatsApp da loja com o resumo completo.

## 3. Não-Requisitos do MVP
- **Sem gateway de pagamento**: A plataforma não cobra taxas de transação nem processa cartão online no MVP.
- **Sem API oficial de WhatsApp paga no MVP**: Utiliza-se geração de link `https://wa.me/...` com mensagem formatada. A arquitetura, no entanto, deve prever transição direta para API oficial da Meta (WhatsApp Business Cloud API).
