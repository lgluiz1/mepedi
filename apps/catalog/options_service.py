from decimal import Decimal
import re
from typing import List, Dict, Optional, Tuple
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import OptionGroup, OptionItem, Product


def parse_item_line(line: str) -> Tuple[str, Decimal]:
    """
    Interpreta uma linha de texto com nome e opcional preço adicional.
    Exemplos aceitos:
      - "Calabresa Especial" -> ("Calabresa Especial", Decimal("0.00"))
      - "Camarão (+ R$ 10,00)" -> ("Camarão", Decimal("10.00"))
      - "Borda Vulcão (+9.00)" -> ("Borda Vulcão", Decimal("9.00"))
      - "Nutella Extra (R$ 6,50)" -> ("Nutella Extra", Decimal("6.50"))
      - "Bacon - 4,00" -> ("Bacon", Decimal("4.00"))
    """
    clean_line = line.strip()
    if not clean_line:
        return "", Decimal("0.00")

    # Padrão para identificar preço no final da linha entre parênteses ou após hífen/mais
    # Ex: (+ R$ 10,00) ou (R$ 10,00) ou (+10,00) ou + 10,00 ou - R$ 5,00
    price_pattern = re.compile(
        r'[\(\[\-+]?\s*(?:R\$\s*)?(\d+(?:[.,]\d{1,2})?)\s*[\)\]]?\s*$',
        re.IGNORECASE
    )

    price = Decimal("0.00")
    name = clean_line

    # Procura se tem indicativo de preço no final
    match = re.search(r'(?:[\(\[]\s*(?:\+\s*)?(?:R\$\s*)?(\d+(?:[.,]\d{1,2})?)\s*[\)\]]|\+\s*(?:R\$\s*)?(\d+(?:[.,]\d{1,2})?)|-\s*(?:R\$\s*)?(\d+(?:[.,]\d{1,2})?))\s*$', clean_line, re.IGNORECASE)
    if match:
        raw_price = match.group(1) or match.group(2) or match.group(3)
        if raw_price:
            try:
                price = Decimal(raw_price.replace(',', '.'))
                # Remove a parte de preço do nome
                name = clean_line[:match.start()].strip()
                # Remove parênteses ou caracteres soltos que sobraram
                name = re.sub(r'[\(\[\-+:]+$', '', name).strip()
            except Exception:
                price = Decimal("0.00")

    return name, price


def bulk_create_option_items(group: OptionGroup, text_input: str) -> int:
    """
    Cria múltiplos itens/sabores a partir de texto com quebras de linha ou vírgulas.
    Retorna o número de itens adicionados.
    """
    if not text_input or not text_input.strip():
        return 0

    # Quebra por linha primeiro; se for linha única com vírgulas, quebra por vírgula
    raw_lines = [l.strip() for l in text_input.strip().splitlines() if l.strip()]
    if len(raw_lines) == 1 and ',' in raw_lines[0]:
        lines = [part.strip() for part in raw_lines[0].split(',') if part.strip()]
    else:
        lines = []
        for rl in raw_lines:
            # Se a linha contiver vírgula mas não contiver preço com vírgula (ex: "Calabresa, Mussarela, Bacon")
            if ',' in rl and not re.search(r'\d+,\d{2}', rl):
                lines.extend([p.strip() for p in rl.split(',') if p.strip()])
            else:
                lines.append(rl)

    created_items = []
    current_order = group.items.count()

    for entry in lines:
        name, price = parse_item_line(entry)
        if name:
            current_order += 1
            created_items.append(
                OptionItem(
                    option_group=group,
                    name=name,
                    price=price,
                    is_available=True,
                    order=current_order
                )
            )

    if created_items:
        OptionItem.objects.bulk_create(created_items)

    return len(created_items)


def clone_option_group_to_product(
    source_group: OptionGroup,
    target_product: Product,
    new_name: Optional[str] = None,
    description: Optional[str] = None,
    min_options: Optional[int] = None,
    max_options: Optional[int] = None,
    is_required: Optional[bool] = None,
    selected_item_ids: Optional[List[int]] = None
) -> OptionGroup:
    """
    Clona um grupo de opções de um produto para outro dentro da mesma loja,
    permitindo customizar o nome, limites de escolha (min/max) e selecionar
    apenas os sabores/itens desejados.
    """
    if source_group.store_id != target_product.store_id:
        raise ValidationError("Não é permitido clonar grupos entre lojas diferentes.")

    name = new_name.strip() if new_name and new_name.strip() else source_group.name
    desc = description.strip() if description is not None else source_group.description
    min_opt = min_options if min_options is not None else source_group.min_options
    max_opt = max_options if max_options is not None else source_group.max_options

    if min_opt > max_opt:
        max_opt = min_opt

    if is_required is None:
        req = source_group.is_required or (min_opt > 0)
    else:
        req = is_required or (min_opt > 0)

    next_order = OptionGroup.objects.filter(product=target_product).count() + 1

    with transaction.atomic():
        cloned_group = OptionGroup.objects.create(
            store=target_product.store,
            product=target_product,
            name=name,
            description=desc,
            min_options=min_opt,
            max_options=max_opt,
            is_required=req,
            order=next_order
        )

        source_items_qs = source_group.items.all().order_by('order', 'id')
        if selected_item_ids:
            id_set = {int(i) for i in selected_item_ids if str(i).isdigit()}
            source_items = [it for it in source_items_qs if it.id in id_set]
        else:
            source_items = list(source_items_qs)

        new_items = [
            OptionItem(
                option_group=cloned_group,
                name=it.name,
                price=it.price,
                is_available=it.is_available,
                order=it.order
            )
            for it in source_items
        ]

        if new_items:
            OptionItem.objects.bulk_create(new_items)

    return cloned_group


def clone_all_product_groups(source_product: Product, target_product: Product) -> Tuple[int, int]:
    """
    Clona TODOS os grupos de opções e itens de um produto fonte para o produto alvo.
    Retorna (total_grupos_criados, total_itens_criados).
    """
    if source_product.store_id != target_product.store_id:
        raise ValidationError("Produtos pertencem a lojas diferentes.")

    groups = source_product.option_groups.all().prefetch_related('items').order_by('order', 'id')
    created_groups = 0
    created_items = 0

    with transaction.atomic():
        current_group_order = target_product.option_groups.count()
        for grp in groups:
            current_group_order += 1
            new_grp = OptionGroup.objects.create(
                store=target_product.store,
                product=target_product,
                name=grp.name,
                description=grp.description,
                min_options=grp.min_options,
                max_options=grp.max_options,
                is_required=grp.is_required,
                order=current_group_order
            )
            created_groups += 1

            items_to_add = [
                OptionItem(
                    option_group=new_grp,
                    name=it.name,
                    price=it.price,
                    is_available=it.is_available,
                    order=it.order
                )
                for it in grp.items.all()
            ]
            if items_to_add:
                OptionItem.objects.bulk_create(items_to_add)
                created_items += len(items_to_add)

    return created_groups, created_items


def get_store_template_groups(store, current_product: Optional[Product] = None) -> List[Dict]:
    """
    Retorna todos os grupos de opções da loja que possuem itens, prontos para servirem
    de modelo para clonagem, ordenando primeiro os produtos da mesma categoria.
    """
    qs = OptionGroup.objects.filter(store=store).select_related('product', 'product__category').prefetch_related('items')
    if current_product:
        qs = qs.exclude(product=current_product)

    groups_data = []
    for g in qs:
        item_count = g.items.count()
        if item_count == 0:
            continue

        is_same_cat = bool(current_product and g.product.category_id == current_product.category_id)
        groups_data.append({
            'id': g.id,
            'name': g.name,
            'description': g.description,
            'min_options': g.min_options,
            'max_options': g.max_options,
            'is_required': g.is_required,
            'product_id': g.product_id,
            'product_name': g.product.name,
            'category_id': g.product.category_id,
            'category_name': g.product.category.name if g.product.category else '',
            'is_same_category': is_same_cat,
            'items_count': item_count,
            'items': [
                {
                    'id': it.id,
                    'name': it.name,
                    'price': float(it.price),
                    'is_available': it.is_available,
                }
                for it in g.items.all().order_by('order', 'name')
            ]
        })

    # Ordena: mesma categoria primeiro, depois nome do produto e nome do grupo
    groups_data.sort(key=lambda x: (not x['is_same_category'], x['product_name'].lower(), x['name'].lower()))
    return groups_data
