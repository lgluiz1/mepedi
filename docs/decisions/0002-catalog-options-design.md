# ADR 0002: Modelagem do Catálogo, Produtos e Grupos de Opções

## Data
2026-09-24

## Status
Aceito

## Contexto
O cardápio digital necessita atender a estabelecimentos gastronômicos com grande diversidade de produtos. Além de categorias e produtos básicos, é requisito essencial que o produto possa conter:
1. **Adicionais pagos**: Bacon (+ R$ 5), Queijo (+ R$ 3), Ovo (+ R$ 2).
2. **Remoção de ingredientes sem custo**: Sem cebola, Sem tomate, Sem molho.
3. **Seleção única obrigatória**: Ponto da carne (Mal passado / Ao ponto / Bem passado), Tamanho (Pequeno / Médio / Grande).
4. **Campos livres**: Observação textual pelo cliente ("Colocar bastante bacon e cortar o lanche ao meio").

Ao mesmo tempo, deve-se manter o isolamento lógico multi-loja (Loja A não pode usar categorias ou opções da Loja B) e garantir que o backend seja a fonte da verdade para o cálculo de preços no pedido.

## Decisão
1. **Hierarquia de Modelos**:
   - `Category`: `(StoreBoundedModel)` - Nome, descrição, ordem e status ativo.
   - `Product`: `(StoreBoundedModel)` - Categoria (FK com validação de loja), nome, descrição, preço base (`DecimalField`), imagem, status ativo e ordem.
   - `OptionGroup`: `(StoreBoundedModel)` - Vinculado a um `Product`. Define regras de seleção:
     - `min_options` (ex: 0 para adicionais opcionais, 1 para obrigatórios).
     - `max_options` (ex: 1 para escolha única, 5 para até 5 adicionais).
     - `is_required` (boolean auxiliar).
     - `order`.
   - `OptionItem`: `(TimeStampedModel)` - Vinculado ao `OptionGroup`. Possui nome, preço adicional (`DecimalField`, default 0.00 para remoções/itens inclusos), status disponível e ordem.
2. **Validação de Tenancy em Nível de Modelo e Serializer**:
   - `clean()` e métodos de validação nos serializers garantem que um `Product` não possa ser salvo apontando para uma `Category` pertencente a outra loja.
   - `OptionGroup` sempre herda a loja do seu produto associado.
3. **Endpoint Público de Cardápio Otimizado**:
   - `GET /api/v1/catalog/public/{store_slug}/menu/` retorna em uma única consulta estruturada as categorias ativas com seus produtos ativos, imagens, grupos de opções e itens disponíveis, usando `prefetch_related` para evitar N+1 queries.

## Consequências
- A estrutura acomoda adicionais pagos, remoções sem custo e variações obrigatórias sem criar tabelas separadas para cada tipo.
- Garante total segurança na separação de lojas e integridade referencial.
