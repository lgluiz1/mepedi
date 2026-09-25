from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from stores.models import Store
from catalog.models import Product, OptionItem, OptionGroup
from customers.models import Customer, CustomerAddress, clean_phone_number
from delivery.models import DeliveryZone
from .models import Order, OrderItem, OrderItemOption


class OrderService:
    """
    Camada de serviço responsável por orquestrar a validação, recálculo financeiro
    e criação atômica de pedidos com segurança absoluta contra manipulação de preços.
    """

    @classmethod
    @transaction.atomic
    def create_order(
        cls,
        store: Store,
        customer_payload: dict,
        delivery_type: str,
        address_payload: dict = None,
        payment_method: str = 'PIX',
        change_for: Decimal = None,
        items_payload: list = None,
        order_notes: str = ''
    ) -> Order:
        """
        Cria um novo pedido após rigoroso recálculo e validação server-side.
        """
        if not items_payload:
            raise ValidationError("O pedido deve conter ao menos um item.")

        # 1. Validação de status da loja
        if not store.is_currently_open():
            raise ValidationError(
                f"O estabelecimento {store.name} está fechado ou temporariamente pausado no momento."
            )

        # 2. Validação da modalidade de entrega
        if delivery_type == Order.TYPE_DELIVERY:
            if not store.allows_delivery:
                raise ValidationError("Este estabelecimento não realiza entregas no momento.")
            if not address_payload or not address_payload.get('street') or not address_payload.get('number'):
                raise ValidationError("Endereço de entrega completo é obrigatório para modalidade Delivery.")
        elif delivery_type == Order.TYPE_PICKUP:
            if not store.allows_pickup:
                raise ValidationError("Este estabelecimento não permite retirada no local.")
        else:
            raise ValidationError(f"Modalidade de entrega inválida: {delivery_type}")

        # 3. Identificação ou criação do Cliente
        phone = clean_phone_number(customer_payload.get('phone', ''))
        name = customer_payload.get('name', '').strip()
        if not phone or not name:
            raise ValidationError("Nome e telefone celular são obrigatórios para identificar o cliente.")

        customer, _ = Customer.objects.get_or_create(
            store=store,
            phone=phone,
            defaults={
                'name': name,
                'document': customer_payload.get('document', ''),
                'email': customer_payload.get('email', '')
            }
        )

        # Atualiza nome se fornecido
        if name and customer.name != name:
            customer.name = name
            customer.save()

        # Se for delivery, salva ou atualiza endereço do cliente
        if delivery_type == Order.TYPE_DELIVERY and address_payload:
            CustomerAddress.objects.get_or_create(
                customer=customer,
                street=address_payload.get('street', ''),
                number=address_payload.get('number', ''),
                neighborhood=address_payload.get('neighborhood', ''),
                city=address_payload.get('city', ''),
                state=address_payload.get('state', '').upper(),
                defaults={
                    'complement': address_payload.get('complement', ''),
                    'postal_code': address_payload.get('postal_code', ''),
                    'reference': address_payload.get('reference', ''),
                    'is_default': True
                }
            )

        # 4. Geração sequencial de order_number da loja
        last_order = Order.objects.filter(store=store).select_for_update().order_by('-order_number').first()
        next_order_number = (last_order.order_number + 1) if last_order else 1001

        # 5. Cálculo do Frete
        delivery_fee = Decimal('0.00')
        if delivery_type == Order.TYPE_DELIVERY:
            if hasattr(store, 'fixed_delivery_fee') and store.fixed_delivery_fee is not None and store.fixed_delivery_fee > Decimal('0.00'):
                delivery_fee = store.fixed_delivery_fee
            else:
                neighborhood = address_payload.get('neighborhood', '').strip()
                zones = DeliveryZone.objects.filter(store=store, is_active=True)
                matched_zone = None
                for zone in zones:
                    if zone.match_neighborhood(neighborhood):
                        matched_zone = zone
                        break
                if matched_zone:
                    delivery_fee = matched_zone.fee
                elif zones.exists():
                    delivery_fee = zones.first().fee

        # 6. Criação do cabeçalho inicial do Pedido
        order = Order(
            store=store,
            customer=customer,
            order_number=next_order_number,
            status=Order.STATUS_NEW,
            delivery_type=delivery_type,
            payment_method=payment_method,
            change_for=change_for,
            delivery_fee=delivery_fee,
            subtotal=Decimal('0.00'),
            total=Decimal('0.00'),
            notes=order_notes,
            # Endereço congelado
            street=address_payload.get('street', '') if address_payload else '',
            number=address_payload.get('number', '') if address_payload else '',
            complement=address_payload.get('complement', '') if address_payload else '',
            neighborhood=address_payload.get('neighborhood', '') if address_payload else '',
            city=address_payload.get('city', '') if address_payload else '',
            state=address_payload.get('state', '').upper() if address_payload else '',
            postal_code=address_payload.get('postal_code', '') if address_payload else '',
            reference=address_payload.get('reference', '') if address_payload else ''
        )
        order.save()

        # 7. Recálculo e inserção dos Itens e Opções
        accumulated_subtotal = Decimal('0.00')

        for item_data in items_payload:
            product_id = item_data.get('product_id')
            quantity = int(item_data.get('quantity', 1))
            if quantity <= 0:
                raise ValidationError("A quantidade do produto deve ser maior que zero.")

            # Busca produto ativo e pertencente à loja
            try:
                product = Product.objects.get(id=product_id, store=store, is_active=True)
            except Product.DoesNotExist:
                raise ValidationError(f"Produto #{product_id} não encontrado ou indisponível nesta loja.")

            unit_price = product.price
            item_notes = item_data.get('notes', '').strip()
            options_payload = item_data.get('options', [])

            # Validação e busca das opções reais no banco
            options_total_unit = Decimal('0.00')
            valid_options_records = []

            for opt_data in options_payload:
                option_id = opt_data.get('id') if isinstance(opt_data, dict) else opt_data
                try:
                    option_item = OptionItem.objects.select_related('option_group').get(
                        id=option_id,
                        option_group__product=product,
                        is_available=True
                    )
                except OptionItem.DoesNotExist:
                    raise ValidationError(f"Opção #{option_id} inválida ou indisponível para o produto {product.name}.")

                options_total_unit += option_item.price
                valid_options_records.append(option_item)

            item_unit_with_options = unit_price + options_total_unit
            item_total = item_unit_with_options * quantity
            item_subtotal = unit_price * quantity

            accumulated_subtotal += item_total

            # Cria OrderItem com preços congelados
            order_item = OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                unit_price=unit_price,
                quantity=quantity,
                subtotal=item_subtotal,
                total=item_total,
                notes=item_notes
            )

            # Cria OrderItemOption para cada adicional
            for opt_record in valid_options_records:
                OrderItemOption.objects.create(
                    order_item=order_item,
                    option_item=opt_record,
                    name=opt_record.name,
                    price=opt_record.price,
                    group_name=opt_record.option_group.name
                )

        # 8. Validação de Pedido Mínimo da Loja
        if store.minimum_order_value > Decimal('0.00'):
            if accumulated_subtotal < store.minimum_order_value:
                raise ValidationError(
                    f"O valor mínimo para pedidos neste estabelecimento é de R$ {store.minimum_order_value:.2f}."
                )

        # 9. Consolidação Final dos Totais
        order.subtotal = accumulated_subtotal
        order.total = accumulated_subtotal + delivery_fee
        order.save(update_fields=['subtotal', 'total'])

        # 10. Atualização das métricas do cliente
        customer.orders_count += 1
        customer.total_spent += order.total
        customer.save(update_fields=['orders_count', 'total_spent'])

        return order
