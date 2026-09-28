from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from stores.models import Store
from catalog.models import Product, OptionItem, OptionGroup
from catalog.services import StockService
from customers.models import Customer, CustomerAddress, clean_phone_number
from delivery.models import DeliveryZone
from .models import Order, OrderItem, OrderItemOption, Coupon, Table, TableSession


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

    @classmethod
    @transaction.atomic
    def get_or_create_table_session(cls, table: Table) -> tuple[TableSession, bool]:
        """
        Obtém a comanda/sessão aberta da mesa ou cria uma nova com segurança transacional.
        """
        session = TableSession.objects.filter(
            table=table,
            status__in=[TableSession.STATUS_OPEN, TableSession.STATUS_WAITING_PAYMENT]
        ).select_for_update().first()

        if session:
            return session, False

        session = TableSession.objects.create(
            store=table.store,
            table=table,
            status=TableSession.STATUS_OPEN
        )
        return session, True

    @classmethod
    @transaction.atomic
    def bind_table_session_to_customer(
        cls,
        store: Store,
        table: Table,
        phone: str = None,
        name: str = None,
        pin_attempt: str = None
    ) -> dict:
        """
        Vincula um cliente e PIN (últimos 4 dígitos do celular) à sessão da mesa.
        Se a mesa já estiver aberta por outra pessoa, exige o PIN para autorizar.
        """
        session, is_new = cls.get_or_create_table_session(table)
        clean_phone = clean_phone_number(phone) if phone else ''
        name_clean = (name or '').strip()
        pin_attempt = (pin_attempt or '').strip()

        # Caso 1: A sessão já possui um titular e PIN configurado
        if session.customer_phone and session.pin_code:
            # Se o próprio titular está informando o mesmo telefone ou o PIN correto
            if (clean_phone and clean_phone == session.customer_phone) or (pin_attempt and pin_attempt == session.pin_code):
                return {
                    'success': True,
                    'is_new_session': False,
                    'customer_name': session.customer_name,
                    'customer_phone': session.customer_phone,
                    'pin_code': session.pin_code,
                    'session_id': str(session.public_id),
                    'message': f"Acesso liberado à comanda da Mesa {table.number}!"
                }

            # Se informou PIN errado
            if pin_attempt and pin_attempt != session.pin_code:
                return {
                    'success': False,
                    'error': "Senha da comanda incorreta. Digite os 4 últimos dígitos do celular do titular da mesa.",
                    'need_pin': True,
                    'titular_name': session.customer_name or "Titular da Mesa"
                }

            # Precisa pedir o PIN
            return {
                'success': False,
                'need_pin': True,
                'titular_name': session.customer_name or "Titular da Mesa",
                'message': f"Esta mesa já está aberta no nome de {session.customer_name or 'outro cliente'}. Digite os 4 últimos dígitos do celular dele para acessar."
            }

        # Caso 2: Sessão aberta mas ainda sem cliente titular vinculado
        if not clean_phone or len(clean_phone) < 8:
            return {
                'success': False,
                'error': "Por favor, informe seu número de WhatsApp com DDD para abrir a comanda."
            }

        # Procura ou cadastra o cliente no CRM da loja
        customer = Customer.objects.filter(store=store, phone=clean_phone).first()
        if customer:
            if name_clean and customer.name != name_clean:
                customer.name = name_clean
                customer.save(update_fields=['name'])
        else:
            customer = Customer.objects.create(
                store=store,
                phone=clean_phone,
                name=name_clean or f"Cliente Mesa {table.number}"
            )

        pin_code = clean_phone[-4:]

        session.customer = customer
        session.customer_name = customer.name
        session.customer_phone = clean_phone
        session.pin_code = pin_code
        session.save(update_fields=['customer', 'customer_name', 'customer_phone', 'pin_code'])

        return {
            'success': True,
            'is_new_session': is_new,
            'customer_name': session.customer_name,
            'customer_phone': session.customer_phone,
            'pin_code': pin_code,
            'session_id': str(session.public_id),
            'message': f"Comanda da Mesa {table.number} aberta com sucesso! Sua senha é {pin_code}."
        }

    @classmethod
    @transaction.atomic
    def create_table_order(
        cls,
        store: Store,
        table: Table,
        session: TableSession,
        items_payload: list,
        customer_name: str = None,
        customer_phone: str = None,
        pin_code: str = None,
        order_notes: str = ''
    ) -> Order:
        """
        Registra itens solicitados pela mesa.
        Se a mesa já possui um pedido ativo, anexa os novos itens como uma nova rodada
        na mesma comanda e pedido, marcando cada novo item como PENDING (Aguardando Cozinha).
        """
        from django.db.models import Max

        if not items_payload:
            raise ValidationError("O pedido da mesa deve conter ao menos um item.")

        if not table.is_active:
            raise ValidationError("Esta mesa está desativada no momento.")

        if session.status not in [TableSession.STATUS_OPEN, TableSession.STATUS_WAITING_PAYMENT]:
            raise ValidationError("A comanda desta mesa já foi encerrada ou cancelada.")

        # Validação do PIN da Mesa (se configurado)
        if session.pin_code:
            provided_pin = str(pin_code or '').strip()
            if not provided_pin and customer_phone:
                sent_clean = clean_phone_number(customer_phone)
                if sent_clean and len(sent_clean) >= 4:
                    provided_pin = sent_clean[-4:]

            if provided_pin != session.pin_code:
                raise ValidationError("Senha da comanda incorreta. Digite os 4 últimos dígitos do celular do titular da mesa.")

        # Se a mesa estava aguardando pagamento e pediu novos itens, reabre para EM CONSUMO
        if session.status == TableSession.STATUS_WAITING_PAYMENT:
            session.status = TableSession.STATUS_OPEN
            session.save(update_fields=['status'])

        # 1. Identificação do Cliente
        clean_phone = clean_phone_number(customer_phone) if customer_phone else (session.customer_phone or '')
        name_clean = (customer_name or session.customer_name or f"Mesa {table.number}").strip()

        if clean_phone:
            customer, _ = Customer.objects.get_or_create(
                store=store,
                phone=clean_phone,
                defaults={'name': name_clean}
            )
            if name_clean and customer.name != name_clean:
                customer.name = name_clean
                customer.save(update_fields=['name'])
        else:
            table_phone = f"8888{table.id:06d}"[:11]
            customer, _ = Customer.objects.get_or_create(
                store=store,
                phone=table_phone,
                defaults={'name': name_clean}
            )

        # Se a sessão ainda não possuía titular vinculado ou PIN, salva os dados agora
        session_updates = []
        if not session.customer and customer:
            session.customer = customer
            session_updates.append('customer')
        if not session.customer_name and customer.name:
            session.customer_name = customer.name
            session_updates.append('customer_name')
        if not session.customer_phone and clean_phone:
            session.customer_phone = clean_phone
            session_updates.append('customer_phone')
        if not session.pin_code and clean_phone:
            session.pin_code = clean_phone[-4:]
            session_updates.append('pin_code')
        if session_updates:
            session.save(update_fields=session_updates)

        # 2. Localiza pedido ativo existente na sessão para anexar itens ou cria um novo
        existing_order = session.orders.exclude(
            status__in=[Order.STATUS_CANCELLED, Order.STATUS_COMPLETED]
        ).order_by('created_at').first()

        is_appending = existing_order is not None

        if is_appending:
            order = existing_order
            # Identifica a próxima rodada
            max_round = order.items.aggregate(Max('batch_round'))['batch_round__max'] or 1
            current_round = max_round + 1
            if order_notes:
                order.notes = f"{order.notes}\n[Rodada #{current_round}]: {order_notes}".strip()
        else:
            current_round = 1
            next_order_number = cls.get_next_order_number(store)
            order = Order(
                store=store,
                customer=customer,
                order_number=next_order_number,
                origin=Order.ORIGIN_TABLE,
                status=Order.STATUS_NEW,
                delivery_type=Order.TYPE_DINE_IN,
                table=table,
                table_session=session,
                payment_method=Order.PAY_OTHER,
                delivery_fee=Decimal('0.00'),
                subtotal=Decimal('0.00'),
                discount=Decimal('0.00'),
                total=Decimal('0.00'),
                notes=order_notes
            )
            order.save()

        # 3. Inserção de itens da rodada com baixa de estoque
        accumulated_new_subtotal = Decimal('0.00')

        for item_data in items_payload:
            product_id = item_data.get('product_id')
            quantity = int(item_data.get('quantity', 1))
            if quantity <= 0:
                raise ValidationError("A quantidade do produto deve ser maior que zero.")

            try:
                product = Product.objects.get(id=product_id, store=store, is_active=True)
            except Product.DoesNotExist:
                raise ValidationError(f"Produto #{product_id} não encontrado ou indisponível nesta loja.")

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

            accumulated_new_subtotal += item_total

            order_item = OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                unit_price=unit_price,
                quantity=quantity,
                subtotal=item_subtotal,
                total=item_total,
                notes=item_notes,
                status=OrderItem.STATUS_PENDING,
                batch_round=current_round
            )

            for opt_record in valid_options_records:
                OrderItemOption.objects.create(
                    order_item=order_item,
                    option_item=opt_record,
                    name=opt_record.name,
                    price=opt_record.price,
                    group_name=opt_record.option_group.name
                )

            # Baixa atômica de estoque
            StockService.decrement_stock(
                product=product,
                quantity=quantity,
                order=order,
                origin='TABLE'
            )

        order.subtotal += accumulated_new_subtotal
        order.total += accumulated_new_subtotal
        if is_appending:
            order.status = Order.STATUS_PREPARING
            order.save(update_fields=['subtotal', 'total', 'notes', 'status'])
        else:
            order.save(update_fields=['subtotal', 'total', 'notes'])

        # 4. Transmissão em tempo real via WebSocket
        try:
            from .consumers import broadcast_order_event
            from .serializers import OrderDetailSerializer
            order_data = OrderDetailSerializer(order).data
            event_name = 'ORDER_ITEMS_ADDED' if is_appending else 'ORDER_CREATED'
            broadcast_order_event(store.id, event_name, order_data)
            if is_appending:
                # Também emite ORDER_UPDATED para garantir compatibilidade imediata com todos os painéis
                broadcast_order_event(store.id, 'ORDER_UPDATED', order_data)
        except Exception as ws_err:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao transmitir WebSocket {event_name} (Mesa): {ws_err}")

        return order

    @classmethod
    @transaction.atomic
    def update_order_item_status(
        cls,
        store: Store,
        order_item_id: int,
        new_status: str
    ) -> OrderItem:
        """
        Atualiza o status de preparo de um item individual (PENDING, PREPARING, READY, SERVED, CANCELLED).
        Se for cancelado, realiza o estorno de estoque do item e subtrai do total do pedido.
        """
        valid_statuses = [
            OrderItem.STATUS_PENDING,
            OrderItem.STATUS_PREPARING,
            OrderItem.STATUS_READY,
            OrderItem.STATUS_SERVED,
            OrderItem.STATUS_CANCELLED
        ]
        if new_status not in valid_statuses:
            raise ValidationError(f"Status '{new_status}' inválido para item de pedido.")

        order_item = OrderItem.objects.select_for_update(of=('self',)).select_related('order').get(
            id=order_item_id,
            order__store=store
        )
        old_status = order_item.status
        if old_status == new_status:
            return order_item

        # Estorno de estoque caso o item seja cancelado
        if new_status == OrderItem.STATUS_CANCELLED and old_status != OrderItem.STATUS_CANCELLED:
            if order_item.product and order_item.product.track_stock:
                from catalog.models import StockMovement
                StockMovement.objects.create(
                    store=store,
                    product=order_item.product,
                    movement_type=StockMovement.TYPE_ENTRY,
                    quantity=order_item.quantity,
                    notes=f"Estorno de item cancelado na comanda da {order_item.order.formatted_delivery_address} (#{order_item.order.order_number})"
                )
                order_item.product.stock_quantity += order_item.quantity
                order_item.product.save(update_fields=['stock_quantity'])

            # Recalcula total do pedido subtraindo o item cancelado
            order = order_item.order
            order.subtotal = max(Decimal('0.00'), order.subtotal - order_item.total)
            order.total = max(Decimal('0.00'), order.total - order_item.total)
            order.save(update_fields=['subtotal', 'total'])

        order_item.status = new_status
        order_item.save(update_fields=['status'])

        # Sincroniza o status macro do pedido
        order = order_item.order
        all_items = order.items.exclude(status=OrderItem.STATUS_CANCELLED)
        if all_items.exists():
            if all(it.status == OrderItem.STATUS_SERVED for it in all_items):
                # Pedidos de mesa permanecem 'Na Mesa' (SAIU_PARA_ENTREGA) até a comanda ser fechada/paga
                order.status = Order.STATUS_OUT_FOR_DELIVERY if order.origin == Order.ORIGIN_TABLE else Order.STATUS_COMPLETED
                order.save(update_fields=['status'])
            elif all(it.status in [OrderItem.STATUS_READY, OrderItem.STATUS_SERVED] for it in all_items):
                order.status = Order.STATUS_READY
                order.save(update_fields=['status'])
            elif any(it.status == OrderItem.STATUS_PREPARING for it in all_items):
                order.status = Order.STATUS_PREPARING
                order.save(update_fields=['status'])

        # Notifica WebSocket
        try:
            from .consumers import broadcast_order_event
            from .serializers import OrderDetailSerializer
            broadcast_order_event(store.id, 'ORDER_UPDATED', OrderDetailSerializer(order).data)
        except Exception as ws_err:
            pass

        return order_item

    @classmethod
    @transaction.atomic
    def request_table_bill(cls, session: TableSession) -> TableSession:
        """
        Cliente solicita o fechamento da conta na mesa.
        Atualiza o status para WAITING_PAY e notifica a equipe do salão/caixa em tempo real.
        """
        from django.utils import timezone

        locked_session = TableSession.objects.select_for_update().get(id=session.id)
        if locked_session.status != TableSession.STATUS_OPEN:
            raise ValidationError("Esta mesa não possui comanda aberta em consumo.")

        locked_session.status = TableSession.STATUS_WAITING_PAYMENT
        locked_session.bill_requested_at = timezone.now()
        locked_session.save(update_fields=['status', 'bill_requested_at'])

        try:
            from .consumers import broadcast_order_event
            broadcast_order_event(locked_session.store_id, 'TABLE_BILL_REQUESTED', {
                'table_id': locked_session.table_id,
                'table_number': locked_session.table.number,
                'customer_name': locked_session.customer_name,
                'session_id': str(locked_session.public_id),
                'total': float(locked_session.calculate_total()),
            })
        except Exception as ws_err:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao transmitir WebSocket TABLE_BILL_REQUESTED: {ws_err}")

        return locked_session

    @classmethod
    @transaction.atomic
    def close_table_session(
        cls,
        session_id,
        operator,
        payment_method: str = Order.PAY_PIX,
        discount: Decimal = Decimal('0.00'),
        notes: str = ''
    ) -> TableSession:
        """
        Encerramento atômico definitivo da sessão/comanda da mesa pelo PDV ou Garçom.
        Bloqueia via select_for_update para evitar encerramento concorrente / pagamento duplicado.
        """
        from django.utils import timezone

        locked_session = TableSession.objects.select_for_update().get(id=session_id)
        if locked_session.status in [TableSession.STATUS_CLOSED, TableSession.STATUS_CANCELLED]:
            raise ValidationError("Esta mesa/comanda já foi encerrada ou cancelada.")

        # Soma os valores válidos
        subtotal = locked_session.calculate_subtotal()
        disc = Decimal(str(discount or '0.00'))
        final_total = max(Decimal('0.00'), subtotal - disc)

        # Atualiza todos os pedidos da mesa para CONCLUIDO e com a forma de pagamento selecionada
        valid_orders = locked_session.get_valid_orders()
        for ord in valid_orders:
            if ord.status != Order.STATUS_CANCELLED:
                ord.status = Order.STATUS_COMPLETED
                ord.payment_method = payment_method
                ord.save(update_fields=['status', 'payment_method'])

        locked_session.status = TableSession.STATUS_CLOSED
        locked_session.closed_at = timezone.now()
        locked_session.closed_by = operator
        locked_session.payment_method = payment_method
        locked_session.discount = disc
        locked_session.total_paid = final_total
        locked_session.notes = notes
        locked_session.save()

        try:
            from .consumers import broadcast_order_event
            broadcast_order_event(locked_session.store_id, 'TABLE_SESSION_CLOSED', {
                'table_id': locked_session.table_id,
                'table_number': locked_session.table.number,
                'session_id': str(locked_session.public_id),
                'total_paid': float(final_total),
            })
        except Exception as ws_err:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao transmitir WebSocket TABLE_SESSION_CLOSED: {ws_err}")

        return locked_session



