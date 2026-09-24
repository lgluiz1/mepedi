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
- `stores`: Cadastro da loja, endereço comercial, slug público, horários de funcionamento.
- `catalog`: Categorias, produtos, adicionais, regras de opções (mínimo/máximo) e disponibilidade.
- `customers`: Clientes por loja identificados pelo telefone, endereços de entrega salvos.
- `orders`: Cabeçalho do pedido, itens, opções selecionadas, status e totais recalculados.
- `delivery`: Formas de entrega (retirada vs entrega), zonas e taxas de entrega.
- `whatsapp`: Formatação de mensagens pré-preenchidas e link dinâmico para WhatsApp.
- `core`: Classes base abstratas, decorators, validações globais e utilitários.
