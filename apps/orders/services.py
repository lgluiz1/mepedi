from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from stores.models import Store
from catalog.models import Product, OptionItem, OptionGroup
from catalog.services import StockService
from customers.models import Customer, CustomerAddress, clean_phone_number
from delivery.models import DeliveryZone
from .models import Order, OrderItem, OrderItemOption, Coupon


class OrderService:
    """
    Camada de serviço responsável por orquestrar a validação, recálculo financeiro,
    estoque unificado, cupons promocionais e criação atômica de pedidos (Online e PDV).
    """

    @classmethod
    def get_next_order_number(cls, store: Store) -> int:
        """
        Obtém com segurança atômica (select_for_update) o próximo número sequencial da loja.
        Garante que Pedidos Online e PDV utilizem a MESMA sequência global (#1001, #1002...).
        """
        last_order = Order.objects.filter(store=store).select_for_update().order_by('-order_number').first()
        return (last_order.order_number + 1) if last_order else 1001

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
        order_notes: str = '',
        coupon_code: str = None
    ) -> Order:
        """
        Cria um novo pedido Online após rigoroso recálculo, baixa de estoque e aplicação de cupom.
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

        if name and customer.name != name:
            customer.name = name
            customer.save()

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

        # 4. Geração sequencial atômica de order_number da loja
        next_order_number = cls.get_next_order_number(store)

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
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_NEW,
            delivery_type=delivery_type,
            payment_method=payment_method,
            change_for=change_for,
            delivery_fee=delivery_fee,
            subtotal=Decimal('0.00'),
            discount=Decimal('0.00'),
            total=Decimal('0.00'),
            notes=order_notes,
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

        # 7. Recálculo e inserção dos Itens e Opções com baixa de estoque
        accumulated_subtotal = Decimal('0.00')

        for item_data in items_payload:
            product_id = item_data.get('product_id')
            quantity = int(item_data.get('quantity', 1))
            if quantity <= 0:
                raise ValidationError("A quantidade do produto deve ser maior que zero.")

            try:
                product = Product.objects.get(id=product_id, store=store, is_active=True)
            except Product.DoesNotExist:
                raise ValidationError(f"Produto #{product_id} não encontrado ou indisponível nesta loja.")

            # Aplicação do Preço Promocional quando ativo
            unit_price = product.current_price
            item_notes = item_data.get('notes', '').strip()
            options_payload = item_data.get('options', [])

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

            # Baixa no estoque centralizado
            StockService.decrement_stock(
                product=product,
                quantity=quantity,
                order=order,
                origin=Order.ORIGIN_ONLINE
            )

        # 8. Validação de Pedido Mínimo da Loja
        if store.minimum_order_value > Decimal('0.00'):
            if accumulated_subtotal < store.minimum_order_value:
                raise ValidationError(
                    f"O valor mínimo para pedidos neste estabelecimento é de R$ {store.minimum_order_value:.2f}."
                )

        # 9. Aplicação de Cupom de Desconto (se fornecido)
        discount_amount = Decimal('0.00')
        coupon_obj = None
        if coupon_code:
            code_clean = coupon_code.strip().upper()
            try:
                coupon_obj = Coupon.objects.select_for_update().get(store=store, code=code_clean, is_active=True)
                is_valid, err_msg = coupon_obj.validate_for_order(accumulated_subtotal, delivery_fee)
                if not is_valid:
                    raise ValidationError(err_msg)
                discount_amount = coupon_obj.calculate_discount(accumulated_subtotal, delivery_fee)
                coupon_obj.times_used += 1
                coupon_obj.save(update_fields=['times_used'])
            except Coupon.DoesNotExist:
                raise ValidationError(f"Cupom de desconto '{coupon_code}' inválido ou não encontrado.")

        # 10. Consolidação Final dos Totais
        order.subtotal = accumulated_subtotal
        order.discount = discount_amount
        order.coupon = coupon_obj
        order.coupon_code = coupon_obj.code if coupon_obj else ''
        order.total = max(Decimal('0.00'), accumulated_subtotal + delivery_fee - discount_amount)
        order.save(update_fields=['subtotal', 'discount', 'total', 'coupon', 'coupon_code'])

        # 11. Atualização das métricas do cliente
        customer.orders_count += 1
        customer.total_spent += order.total
        customer.save(update_fields=['orders_count', 'total_spent'])

        # 12. Broadcast via WebSocket para atualização em tempo real no Painel
        try:
            from .consumers import broadcast_order_event
            from .serializers import OrderDetailSerializer
            broadcast_order_event(store.id, 'ORDER_CREATED', OrderDetailSerializer(order).data)
        except Exception as ws_err:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao transmitir WebSocket ORDER_CREATED: {ws_err}")

        return order

    @classmethod
    @transaction.atomic
    def create_pos_order(
        cls,
        store: Store,
        operator,
        items_payload: list,
        payment_method: str = Order.PAY_MONEY,
        change_for: Decimal = None,
        customer_name: str = None,
        customer_phone: str = None,
        coupon_code: str = None,
        order_notes: str = ''
    ) -> Order:
        """
        Cria um novo pedido presencial no PDV Balcão, compartilhando a mesma sequência global
        de numeração e o mesmo estoque unificado.
        """
        if not items_payload:
            raise ValidationError("O pedido do PDV deve conter ao menos um item.")

        # 1. Identificação do Cliente (Opcional no PDV: Balcão por padrão)
        clean_phone = clean_phone_number(customer_phone) if customer_phone else ''
        name_clean = customer_name.strip() if customer_name else ''

        if clean_phone:
            customer, _ = Customer.objects.get_or_create(
                store=store,
                phone=clean_phone,
                defaults={'name': name_clean or 'Cliente Balcão'}
            )
            if name_clean and customer.name != name_clean:
                customer.name = name_clean
                customer.save(update_fields=['name'])
        else:
            # Venda presencial sem telefone: cliente padrão do PDV da loja (somente dígitos)
            pos_phone = f"0000{store.id:06d}"[:11]
            customer, _ = Customer.objects.get_or_create(
                store=store,
                phone=pos_phone,
                defaults={'name': name_clean or 'Venda Balcão'}
            )
            if name_clean and customer.name != name_clean:
                customer.name = name_clean
                customer.save(update_fields=['name'])

        # 2. Mesma sequência global de pedidos (#1001, #1002...)
        next_order_number = cls.get_next_order_number(store)

        # 3. Criação do Pedido PDV já finalizado/pronto
        order = Order(
            store=store,
            customer=customer,
            order_number=next_order_number,
            origin=Order.ORIGIN_PDV,
            operator=operator,
            status=Order.STATUS_COMPLETED,
            delivery_type=Order.TYPE_PICKUP,
            payment_method=payment_method,
            change_for=change_for,
            delivery_fee=Decimal('0.00'),
            subtotal=Decimal('0.00'),
            discount=Decimal('0.00'),
            total=Decimal('0.00'),
            notes=order_notes
        )
        order.save()

        # 4. Inserção de Itens, Adicionais e Baixa Atômica no MESMO Estoque
        accumulated_subtotal = Decimal('0.00')

        for item_data in items_payload:
            product_id = item_data.get('product_id')
            quantity = int(item_data.get('quantity', 1))
            if quantity <= 0:
                raise ValidationError("A quantidade do produto deve ser maior que zero.")

            try:
                product = Product.objects.get(id=product_id, store=store, is_active=True)
            except Product.DoesNotExist:
                raise ValidationError(f"Produto #{product_id} não encontrado ou indisponível nesta loja.")

            # Aplicação do Preço Promocional quando ativo
            unit_price = product.current_price
            item_notes = item_data.get('notes', '').strip()
            options_payload = item_data.get('options', [])

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
                    raise ValidationError(f"Opção #{option_id} inválida para o produto {product.name}.")

                options_total_unit += option_item.price
                valid_options_records.append(option_item)

            item_unit_with_options = unit_price + options_total_unit
            item_total = item_unit_with_options * quantity
            item_subtotal = unit_price * quantity

            accumulated_subtotal += item_total

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

            for opt_record in valid_options_records:
                OrderItemOption.objects.create(
                    order_item=order_item,
                    option_item=opt_record,
                    name=opt_record.name,
                    price=opt_record.price,
                    group_name=opt_record.option_group.name
                )

            # Baixa no MESMO estoque centralizado com registro do operador no log
            StockService.decrement_stock(
                product=product,
                quantity=quantity,
                order=order,
                user=operator,
                origin=Order.ORIGIN_PDV
            )

        # 5. Aplicação de Cupom de Desconto no PDV (opcional)
        discount_amount = Decimal('0.00')
        coupon_obj = None
        if coupon_code:
            code_clean = coupon_code.strip().upper()
            try:
                coupon_obj = Coupon.objects.select_for_update().get(store=store, code=code_clean, is_active=True)
                is_valid, err_msg = coupon_obj.validate_for_order(accumulated_subtotal, Decimal('0.00'))
                if not is_valid:
                    raise ValidationError(err_msg)
                discount_amount = coupon_obj.calculate_discount(accumulated_subtotal, Decimal('0.00'))
                coupon_obj.times_used += 1
                coupon_obj.save(update_fields=['times_used'])
            except Coupon.DoesNotExist:
                raise ValidationError(f"Cupom '{coupon_code}' não encontrado.")

        # 6. Consolidação dos Totais
        order.subtotal = accumulated_subtotal
        order.discount = discount_amount
        order.coupon = coupon_obj
        order.coupon_code = coupon_obj.code if coupon_obj else ''
        order.total = max(Decimal('0.00'), accumulated_subtotal - discount_amount)
        order.save(update_fields=['subtotal', 'discount', 'total', 'coupon', 'coupon_code'])

        customer.orders_count += 1
        customer.total_spent += order.total
        customer.save(update_fields=['orders_count', 'total_spent'])

        # 7. Broadcast via WebSocket para atualização em tempo real no Painel
        try:
            from .consumers import broadcast_order_event
            from .serializers import OrderDetailSerializer
            broadcast_order_event(store.id, 'ORDER_CREATED', OrderDetailSerializer(order).data)
        except Exception as ws_err:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao transmitir WebSocket ORDER_CREATED (PDV): {ws_err}")

        return order

