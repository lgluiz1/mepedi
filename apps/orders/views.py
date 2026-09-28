from decimal import Decimal
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from django.shortcuts import get_object_or_404, render
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from stores.models import Store
from catalog.services import StockService
from .models import Order, OrderItem, Coupon, Table, TableSession
from .services import OrderService
from .serializers import (
    OrderItemSerializer,
    OrderDetailSerializer,
    CreateOrderRequestSerializer,
    UpdateOrderStatusSerializer,
    UpdateOrderItemStatusSerializer,
    TableSerializer,
    TableSessionDetailSerializer,
    TableIdentifyRequestSerializer,
    CreateTableOrderRequestSerializer,
    CloseTableSessionRequestSerializer
)


class IsStoreMember(permissions.BasePermission):
    message = "Você não possui permissão para acessar os pedidos desta loja."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        store_id = view.kwargs.get('store_id')
        if not store_id:
            return True
        return Store.objects.filter(
            id=store_id,
            memberships__user=request.user,
            memberships__is_active=True
        ).exists()


def get_user_store(user, store_id):
    try:
        return Store.objects.get(
            id=store_id,
            memberships__user=user,
            memberships__is_active=True
        )
    except Store.DoesNotExist:
        raise PermissionDenied("Você não possui permissão para acessar esta loja.")


# =====================================================================
# Endpoints Públicos de Pedidos (Cliente Final)
# =====================================================================

class PublicCreateOrderView(APIView):
    """
    Finalização e criação de novo pedido pelo cliente no cardápio.
    POST /api/v1/orders/public/{store_slug}/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, store_slug):
        store = get_object_or_404(Store, slug=store_slug, is_active=True)
        serializer = CreateOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        try:
            order = OrderService.create_order(
                store=store,
                customer_payload=data['customer'],
                delivery_type=data['delivery_type'],
                address_payload=data.get('address'),
                payment_method=data.get('payment_method', 'PIX'),
                change_for=data.get('change_for'),
                items_payload=data['items'],
                order_notes=data.get('notes', ''),
                coupon_code=data.get('coupon_code')
            )
        except (DjangoValidationError, ValidationError) as e:
            msg = e.messages if hasattr(e, 'messages') else [str(e)]
            return Response({"error": msg[0] if msg else str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Registra evento de Analytics de forma segura e não-bloqueante
        try:
            from analytics.services import AnalyticsService
            from analytics.models import AnalyticsEvent
            session_id = AnalyticsService.get_session_id(request)
            attribution = request.session.get('analytics_attribution') or {}
            AnalyticsService.record_event(
                store=store,
                session_id=session_id,
                event_type=AnalyticsEvent.EVENT_ORDER_CREATED,
                order=order,
                metadata=attribution
            )
        except Exception:
            pass

        return Response(
            OrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED
        )


class PublicOrderDetailView(generics.RetrieveAPIView):
    """
    Consulta pública do status do pedido pelo UUID público.
    GET /api/v1/orders/public/{public_id}/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = OrderDetailSerializer
    lookup_field = 'public_id'
    queryset = Order.objects.all().prefetch_related('items__selected_options', 'customer')


class ValidateCouponView(APIView):
    """
    Validação em tempo real de cupom promocional para Checkout Online e PDV.
    POST /api/v1/orders/coupon/validate/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        store_slug = request.data.get('store_slug')
        store_id = request.data.get('store_id')
        code = request.data.get('code', '').strip().upper()
        subtotal = Decimal(str(request.data.get('subtotal', '0.00') or '0.00'))
        delivery_fee = Decimal(str(request.data.get('delivery_fee', '0.00') or '0.00'))

        if store_slug:
            store = get_object_or_404(Store, slug=store_slug, is_active=True)
        elif store_id:
            store = get_object_or_404(Store, id=store_id, is_active=True)
        else:
            return Response({"valid": False, "error": "Identificador do estabelecimento não informado."}, status=status.HTTP_400_BAD_REQUEST)

        if not code:
            return Response({"valid": False, "error": "Informe o código do cupom."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            coupon = Coupon.objects.get(store=store, code=code, is_active=True)
        except Coupon.DoesNotExist:
            return Response({"valid": False, "error": f"Cupom '{code}' inválido ou inexistente nesta loja."}, status=status.HTTP_400_BAD_REQUEST)

        is_valid, message = coupon.validate_for_order(subtotal, delivery_fee)
        if not is_valid:
            return Response({"valid": False, "error": message}, status=status.HTTP_400_BAD_REQUEST)

        discount = coupon.calculate_discount(subtotal, delivery_fee)
        return Response({
            "valid": True,
            "code": coupon.code,
            "discount_type": coupon.discount_type,
            "discount_value": str(coupon.discount_value),
            "discount_amount": str(discount),
            "message": f"Cupom '{coupon.code}' aplicado com sucesso! Desconto de R$ {discount:.2f}"
        })


# =====================================================================
# Endpoints do Lojista: Gestão e Status dos Pedidos
# =====================================================================

class MerchantOrderListView(generics.ListAPIView):
    """
    Listagem de pedidos da loja com filtros de status e busca.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = OrderDetailSerializer

    def get_queryset(self):
        from django.utils import timezone
        import datetime
        store_id = self.kwargs.get('store_id')
        get_user_store(self.request.user, store_id)

        # Auto-cancela pedidos pendentes que não foram aceitos em até 10 minutos e estorna estoque
        cutoff_10m = timezone.now() - datetime.timedelta(minutes=10)
        expired_orders = Order.objects.filter(store_id=store_id, status=Order.STATUS_NEW, created_at__lt=cutoff_10m)
        for exp_order in expired_orders:
            exp_order.status = Order.STATUS_CANCELLED
            exp_order.save(update_fields=['status'])
            StockService.restore_stock(exp_order)

        qs = Order.objects.filter(store_id=store_id).prefetch_related('items__selected_options', 'customer')
        
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        return qs


class MerchantOrderDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = OrderDetailSerializer
    lookup_field = 'id'

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        get_user_store(self.request.user, store_id)
        return Order.objects.filter(store_id=store_id).prefetch_related('items__selected_options', 'customer')


class MerchantOrderUpdateStatusView(APIView):
    """
    Atualiza o status de um pedido da loja e registra os marcos temporais.
    Caso o pedido seja cancelado, devolve o estoque centralizado com proteção de idempotência.
    PATCH /api/v1/orders/merchant/{store_id}/{id}/status/
    Body: {"status": "ACEITO"}
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def patch(self, request, store_id, id):
        from django.utils import timezone
        store = get_user_store(request.user, store_id)
        order = get_object_or_404(Order, id=id, store=store)

        serializer = UpdateOrderStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data['status']
        now = timezone.now()
        update_fields = ['status', 'updated_at']

        if new_status == Order.STATUS_ACCEPTED:
            if not order.accepted_at:
                order.accepted_at = now
                update_fields.append('accepted_at')
        elif new_status == Order.STATUS_PREPARING:
            if not order.accepted_at:
                order.accepted_at = now
                update_fields.append('accepted_at')
            if not order.preparing_at:
                order.preparing_at = now
                update_fields.append('preparing_at')
        elif new_status == Order.STATUS_READY:
            if not order.ready_at:
                order.ready_at = now
                update_fields.append('ready_at')
        elif new_status == Order.STATUS_CANCELLED:
            # Estorno atômico e idempotente de estoque centralizado
            StockService.restore_stock(order, user=request.user)

        order.status = new_status
        order.save(update_fields=update_fields)

        order_data = OrderDetailSerializer(order, context={'request': request}).data

        # Broadcast WebSocket para atualizar card e métricas no Painel em tempo real
        try:
            from .consumers import broadcast_order_event
            broadcast_order_event(store.id, 'ORDER_UPDATED', order_data)
        except Exception as ws_err:
            import logging
            logging.getLogger(__name__).warning(f"Erro ao transmitir WebSocket ORDER_UPDATED: {ws_err}")

        return Response(order_data)


class POSCreateOrderView(APIView):
    """
    Criação de venda presencial no PDV Balcão pelo operador autenticado da loja.
    POST /api/v1/orders/merchant/{store_id}/pos/
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def post(self, request, store_id):
        store = get_user_store(request.user, store_id)
        data = request.data

        items = data.get('items', [])
        if not items:
            return Response({"error": "Nenhum item adicionado ao carrinho do PDV."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = OrderService.create_pos_order(
                store=store,
                operator=request.user,
                items_payload=items,
                payment_method=data.get('payment_method', Order.PAY_MONEY),
                change_for=Decimal(str(data['change_for']).replace(',', '.')) if data.get('change_for') else None,
                customer_name=data.get('customer_name'),
                customer_phone=data.get('customer_phone'),
                coupon_code=data.get('coupon_code'),
                order_notes=data.get('notes', '')
            )
        except (DjangoValidationError, ValidationError) as e:
            msg = e.messages if hasattr(e, 'messages') else [str(e)]
            return Response({"error": msg[0] if msg else str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)


# =====================================================================
# Views de Template Django (Checkout e Acompanhamento)
# =====================================================================

def public_checkout_page(request, store_slug):
    """
    Renderiza a tela de checkout mobile-first da loja com suporte a identificação do cliente e endereços salvos.
    """
    from customers.models import Customer, clean_phone_number

    store = get_object_or_404(Store, slug=store_slug, is_active=True)
    delivery_zones = store.delivery_zones.filter(is_active=True) if hasattr(store, 'delivery_zones') else []

    phone_raw = request.GET.get('phone') or request.session.get('customer_phone', '')
    clean_phone = clean_phone_number(phone_raw) if phone_raw else ''
    customer = None
    saved_addresses = []

    if clean_phone:
        phone_variations = [clean_phone]
        if clean_phone.startswith('55') and len(clean_phone) in (12, 13):
            phone_variations.append(clean_phone[2:])
        else:
            phone_variations.append(f"55{clean_phone}")
        customer = Customer.objects.filter(store=store, phone__in=phone_variations).prefetch_related('addresses').first()
        if customer:
            saved_addresses = list(customer.addresses.all())

    is_open = store.is_currently_open()
    today_hours = store.get_today_hours_display()
    next_opening_text = store.get_next_opening_text()

    context = {
        'store': store,
        'delivery_zones': delivery_zones,
        'is_open': is_open,
        'status_label': store.status_label,
        'today_hours': today_hours,
        'next_opening_text': next_opening_text,
        'customer': customer,
        'saved_addresses': saved_addresses,
        'current_year': timezone.localtime().year,
    }
    # Registra evento de início de checkout
    try:
        from analytics.services import AnalyticsService
        from analytics.models import AnalyticsEvent
        session_id = AnalyticsService.get_session_id(request)
        AnalyticsService.record_event(
            store=store,
            session_id=session_id,
            event_type=AnalyticsEvent.EVENT_CHECKOUT_STARTED,
            metadata={'path': request.path}
        )
    except Exception:
        pass

    return render(request, 'stores/checkout.html', context)



def public_order_status_page(request, store_slug, public_id):
    """
    Renderiza a página de confirmação e acompanhamento do pedido pelo cliente.
    """
    from whatsapp.services import get_store_order_whatsapp_link

    store = get_object_or_404(Store, slug=store_slug, is_active=True)
    order = get_object_or_404(
        Order.objects.prefetch_related('items__selected_options', 'customer'),
        public_id=public_id,
        store=store
    )
    whatsapp_link = get_store_order_whatsapp_link(order, request=request)
    context = {
        'store': store,
        'order': order,
        'whatsapp_link': whatsapp_link,
    }
    return render(request, 'stores/order_detail.html', context)


def public_customer_orders_page(request, store_slug):
    """
    Página 'Meus Pedidos' do cliente no cardápio digital (estilo Yooga / InstaDelivery).
    Identifica o cliente pelo telefone (WhatsApp) sem exigir senha no primeiro momento.
    Exibe abas 'Em Andamento' e 'Finalizados' com status em tempo real e atalho para o pedido.
    """
    import re
    from customers.models import Customer
    from django.db.models import Q

    store = get_object_or_404(Store, slug=store_slug, is_active=True)

    # Logout / Troca de número
    if request.GET.get('action') == 'logout':
        if 'customer_phone' in request.session:
            del request.session['customer_phone']
        if 'customer_name' in request.session:
            del request.session['customer_name']
        return render(request, 'stores/my_orders.html', {
            'store': store,
            'customer': None,
            'phone': '',
            'active_orders': [],
            'completed_orders': [],
            'active_count': 0,
            'completed_count': 0,
        })

    phone_raw = request.GET.get('phone') or request.POST.get('phone') or request.session.get('customer_phone', '')
    name_raw = request.GET.get('name') or request.POST.get('name') or request.session.get('customer_name', '')

    clean_digits = re.sub(r'\D', '', str(phone_raw)) if phone_raw else ''
    customer = None
    active_orders = []
    completed_orders = []

    if clean_digits:
        # Salva na sessão do cliente
        request.session['customer_phone'] = clean_digits
        if name_raw:
            request.session['customer_name'] = name_raw.strip()

        # Busca flexível por telefone (com ou sem DDI 55)
        phone_variations = [clean_digits]
        if clean_digits.startswith('55') and len(clean_digits) in (12, 13):
            phone_variations.append(clean_digits[2:])
        else:
            phone_variations.append(f"55{clean_digits}")

        customer = Customer.objects.filter(store=store, phone__in=phone_variations).first()

        # Se não existe e informou o nome, registra o cliente
        if not customer and name_raw:
            customer = Customer.objects.create(
                store=store,
                phone=clean_digits,
                name=name_raw.strip()
            )

        if customer:
            # Atualiza nome se foi informado novo nome
            if name_raw and customer.name != name_raw.strip():
                customer.name = name_raw.strip()
                customer.save(update_fields=['name'])

            all_orders = Order.objects.filter(
                store=store,
                customer=customer
            ).prefetch_related('items__selected_options').order_by('-created_at')

            active_statuses = [
                Order.STATUS_NEW,
                Order.STATUS_ACCEPTED,
                Order.STATUS_PREPARING,
                Order.STATUS_READY,
                Order.STATUS_OUT_FOR_DELIVERY,
            ]

            active_orders = [o for o in all_orders if o.status in active_statuses]
            completed_orders = [o for o in all_orders if o.status not in active_statuses]

    context = {
        'store': store,
        'customer': customer,
        'phone': clean_digits,
        'customer_name': customer.name if customer else (name_raw.strip() if name_raw else ''),
        'active_orders': active_orders,
        'completed_orders': completed_orders,
        'active_count': len(active_orders),
        'completed_count': len(completed_orders),
    }
    return render(request, 'stores/my_orders.html', context)


# =====================================================================
# Endpoints de Mesa / Cardápio Digital QR Code (Público)
# =====================================================================

class PublicTableSessionIdentifyView(APIView):
    """
    Identifica o cliente na mesa pelo WhatsApp e PIN (4 dígitos) ou abre a comanda da mesa.
    POST /api/v1/orders/table/<uuid:qr_token>/identify/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, qr_token):
        table = get_object_or_404(Table, qr_token=qr_token, is_active=True)
        store = table.store

        if not store.is_active:
            return Response({"error": "Este estabelecimento está inativo no momento."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = TableIdentifyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = OrderService.bind_table_session_to_customer(
            store=store,
            table=table,
            phone=data.get('phone'),
            name=data.get('name'),
            pin_attempt=data.get('pin')
        )

        status_code = status.HTTP_200_OK if result.get('success') else status.HTTP_400_BAD_REQUEST
        return Response(result, status=status_code)


class PublicTableSessionStatusView(APIView):
    """
    Consulta o estado da comanda da mesa (se está livre, ocupada, com titular ou aguardando PIN).
    GET /api/v1/orders/table/<uuid:qr_token>/session-status/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, qr_token):
        table = get_object_or_404(Table, qr_token=qr_token, is_active=True)
        session = table.current_session

        if not session or not session.customer_phone:
            return Response({
                "is_occupied": False,
                "need_identification": True,
                "table_number": table.number,
                "table_name": table.name,
                "message": f"Mesa {table.number} livre. Informe seu WhatsApp para abrir a comanda."
            })

        # Mascara o telefone deixando apenas os 4 dígitos finais (ex: (**) *****-4321)
        masked_phone = f"(**) *****-{session.pin_code}" if session.pin_code else ""

        return Response({
            "is_occupied": True,
            "need_identification": False,
            "session_id": str(session.public_id),
            "table_number": table.number,
            "table_name": table.name,
            "customer_name": session.customer_name,
            "customer_phone_masked": masked_phone,
            "pin_code": session.pin_code,
            "status": session.status,
            "status_display": session.get_status_display(),
            "subtotal": float(session.calculate_subtotal()),
            "total": float(session.calculate_total()),
            "orders_count": session.get_valid_orders().count(),
            "bill_requested": session.status == TableSession.STATUS_WAITING_PAYMENT,
        })


class PublicCreateTableOrderView(APIView):
    """
    Submissão de rodada de pedido realizada pelo cliente na mesa física via QR Code.
    POST /api/v1/orders/table/<uuid:qr_token>/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, qr_token):
        table = get_object_or_404(Table, qr_token=qr_token, is_active=True)
        store = table.store

        if not store.is_active:
            return Response({"error": "Este estabelecimento está inativo no momento."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CreateTableOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            session, _ = OrderService.get_or_create_table_session(table)
            order = OrderService.create_table_order(
                store=store,
                table=table,
                session=session,
                items_payload=data['items'],
                customer_name=data.get('customer_name', ''),
                customer_phone=data.get('customer_phone', ''),
                pin_code=data.get('pin_code', ''),
                order_notes=data.get('notes', '')
            )
        except (DjangoValidationError, ValidationError) as e:
            msg = e.messages if hasattr(e, 'messages') else [str(e)]
            return Response({"error": msg[0] if msg else str(e)}, status=status.HTTP_400_BAD_REQUEST)

        order_data = OrderDetailSerializer(order).data
        order_data["session_pin"] = session.pin_code
        order_data["session_customer_name"] = session.customer_name
        order_data["session_customer_phone"] = session.customer_phone
        return Response(order_data, status=status.HTTP_201_CREATED)


class PublicTableComandaView(APIView):
    """
    Retorna os dados completos da comanda/sessão de consumo da mesa.
    GET /api/v1/orders/table/<uuid:qr_token>/comanda/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, qr_token):
        table = get_object_or_404(Table, qr_token=qr_token, is_active=True)
        session = table.current_session
        if not session:
            return Response({
                "has_active_session": False,
                "table_number": table.number,
                "table_name": table.name,
                "message": "Nenhum pedido realizado nesta mesa até o momento."
            })

        data = TableSessionDetailSerializer(session).data
        data["has_active_session"] = True
        return Response(data)


class PublicRequestTableBillView(APIView):
    """
    Cliente solicita a conta / encerramento da mesa.
    POST /api/v1/orders/table/<uuid:qr_token>/pedir-conta/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, qr_token):
        table = get_object_or_404(Table, qr_token=qr_token, is_active=True)
        session = table.current_session
        if not session:
            return Response(
                {"error": "Nenhuma comanda aberta nesta mesa para solicitar a conta."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            updated_session = OrderService.request_table_bill(session)
        except (DjangoValidationError, ValidationError) as e:
            msg = e.messages if hasattr(e, 'messages') else [str(e)]
            return Response({"error": msg[0] if msg else str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "success": True,
            "message": "Conta solicitada com sucesso! Um atendente virá à sua mesa.",
            "status": updated_session.status,
            "total": float(updated_session.calculate_total())
        })


class MerchantOrderItemStatusUpdateView(APIView):
    """
    Atualiza o status de preparo de um item individual (PENDING, PREPARING, READY, SERVED, CANCELLED).
    PATCH /api/v1/orders/merchant/<int:store_id>/items/<int:item_id>/status/
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def patch(self, request, store_id, item_id):
        store = get_user_store(request.user, store_id)
        serializer = UpdateOrderItemStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        try:
            item = OrderService.update_order_item_status(
                store=store,
                order_item_id=item_id,
                new_status=new_status
            )
        except (DjangoValidationError, ValidationError, OrderItem.DoesNotExist) as e:
            msg = e.messages if hasattr(e, 'messages') else [str(e)]
            return Response({"error": msg[0] if msg else str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OrderItemSerializer(item).data, status=status.HTTP_200_OK)



# =====================================================================
# Endpoints do Lojista para Gestão de Mesas e Fechamento no PDV
# =====================================================================

class MerchantTableListCreateView(APIView):
    """
    Lista e cria mesas para a loja.
    GET /api/v1/orders/merchant/<int:store_id>/tables/
    POST /api/v1/orders/merchant/<int:store_id>/tables/
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def get(self, request, store_id):
        store = get_user_store(request.user, store_id)
        tables = Table.objects.filter(store=store).order_by('number')
        serializer = TableSerializer(tables, many=True)
        return Response(serializer.data)

    def post(self, request, store_id):
        store = get_user_store(request.user, store_id)
        number = str(request.data.get('number', '')).strip()
        name = str(request.data.get('name', '')).strip()
        is_active = bool(request.data.get('is_active', True))

        if not number:
            return Response({"error": "O número da mesa é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        if Table.objects.filter(store=store, number=number).exists():
            return Response({"error": f"Já existe uma mesa com o número '{number}' nesta loja."}, status=status.HTTP_400_BAD_REQUEST)

        table = Table.objects.create(
            store=store,
            number=number,
            name=name,
            is_active=is_active
        )
        return Response(TableSerializer(table).data, status=status.HTTP_201_CREATED)


class MerchantTableDetailView(APIView):
    """
    Atualiza ou exclui uma mesa da loja.
    PATCH /api/v1/orders/merchant/<int:store_id>/tables/<int:table_id>/
    DELETE /api/v1/orders/merchant/<int:store_id>/tables/<int:table_id>/
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def patch(self, request, store_id, table_id):
        store = get_user_store(request.user, store_id)
        table = get_object_or_404(Table, id=table_id, store=store)

        if 'number' in request.data:
            num = str(request.data['number']).strip()
            if not num:
                return Response({"error": "O número da mesa não pode ser vazio."}, status=status.HTTP_400_BAD_REQUEST)
            if Table.objects.filter(store=store, number=num).exclude(id=table.id).exists():
                return Response({"error": f"Já existe outra mesa com o número '{num}'."}, status=status.HTTP_400_BAD_REQUEST)
            table.number = num

        if 'name' in request.data:
            table.name = str(request.data['name']).strip()

        if 'is_active' in request.data:
            table.is_active = bool(request.data['is_active'])

        table.save()
        return Response(TableSerializer(table).data)

    def delete(self, request, store_id, table_id):
        store = get_user_store(request.user, store_id)
        table = get_object_or_404(Table, id=table_id, store=store)

        if table.orders.exists():
            table.is_active = False
            table.save(update_fields=['is_active'])
            return Response({"detail": "Mesa desativada para manter o histórico de vendas."}, status=status.HTTP_200_OK)

        table.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MerchantActiveSessionByTableView(APIView):
    """
    Retorna a comanda ativa de uma mesa (para consumo imediato no PDV).
    GET /api/v1/orders/merchant/<int:store_id>/tables/<int:table_id>/session/
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def get(self, request, store_id, table_id):
        store = get_user_store(request.user, store_id)
        table = get_object_or_404(Table, id=table_id, store=store)
        sess = table.current_session
        if not sess:
            return Response({"active": False, "message": "Mesa livre no momento."}, status=status.HTTP_200_OK)

        data = TableSessionDetailSerializer(sess).data
        data["active"] = True
        return Response(data)


class MerchantTableSessionCloseView(APIView):
    """
    Encerra comanda/sessão de mesa pelo PDV ou Garçom recebendo o pagamento.
    POST /api/v1/orders/merchant/<int:store_id>/table-sessions/<uuid:session_id>/close/
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def post(self, request, store_id, session_id):
        store = get_user_store(request.user, store_id)
        session = get_object_or_404(TableSession, public_id=session_id, store=store)

        serializer = CloseTableSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            closed_sess = OrderService.close_table_session(
                session_id=session.id,
                operator=request.user,
                payment_method=data.get('payment_method', Order.PAY_PIX),
                discount=Decimal(str(data.get('discount', '0.00'))),
                notes=data.get('notes', '')
            )
        except (DjangoValidationError, ValidationError) as e:
            msg = e.messages if hasattr(e, 'messages') else [str(e)]
            return Response({"error": msg[0] if msg else str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "success": True,
            "session_id": str(closed_sess.public_id),
            "table_number": closed_sess.table.number,
            "total_paid": float(closed_sess.total_paid),
            "status": closed_sess.status
        })


# =====================================================================
# Páginas Web Públicas de Mesa
# =====================================================================

def public_table_menu_page(request, store_slug, qr_token):
    """
    Página pública do Cardápio Digital da Mesa via QR Code.
    Identifica a mesa, abre/recupera a comanda e exibe os produtos com visual mobile-first.
    """
    import json
    from django.db.models import Prefetch
    from catalog.models import Category, Product, OptionGroup, OptionItem

    store = get_object_or_404(Store.objects.prefetch_related('business_hours'), slug=store_slug, is_active=True)
    table = get_object_or_404(Table, store=store, qr_token=qr_token, is_active=True)
    session, _ = OrderService.get_or_create_table_session(table)

    categories = Category.objects.filter(
        store=store,
        is_active=True
    ).prefetch_related(
        Prefetch(
            'products',
            queryset=Product.objects.filter(is_active=True).prefetch_related(
                Prefetch(
                    'option_groups',
                    queryset=OptionGroup.objects.prefetch_related(
                        Prefetch('items', queryset=OptionItem.objects.filter(is_available=True))
                    )
                )
            )
        )
    )

    products_catalog = {}
    for cat in categories:
        for prod in cat.products.all():
            products_catalog[prod.id] = {
                'id': prod.id,
                'code': prod.code or '',
                'name': prod.name,
                'description': prod.description,
                'price': float(prod.price),
                'current_price': float(prod.current_price),
                'is_promotional': prod.is_promotional,
                'promotional_price': float(prod.promotional_price) if prod.promotional_price else None,
                'discount_percent': prod.discount_percent,
                'track_stock': prod.track_stock,
                'stock_quantity': prod.stock_quantity,
                'is_in_stock': prod.is_in_stock,
                'image_url': prod.image.url if prod.image else None,
                'category_id': cat.id,
                'category_name': cat.name,
                'option_groups': [
                    {
                        'id': og.id,
                        'name': og.name,
                        'description': og.description,
                        'min_options': og.min_options,
                        'max_options': og.max_options,
                        'is_required': og.is_required,
                        'items': [
                            {
                                'id': item.id,
                                'name': item.name,
                                'price': float(item.price),
                                'is_available': item.is_available,
                            }
                            for item in og.items.all().order_by('order', 'name')
                        ]
                    }
                    for og in prod.option_groups.all()
                ]
            }

    context = {
        'store': store,
        'table': table,
        'table_session': session,
        'categories': categories,
        'products_catalog_json': json.dumps(products_catalog),
        'is_table_mode': True,
        'is_open': store.is_currently_open(),
        'status_label': store.status_label,
        'current_year': timezone.localtime().year,
    }
    return render(request, 'stores/table_menu.html', context)


def public_table_comanda_page(request, store_slug, qr_token):
    """
    Página do cliente para acompanhar a Comanda da Mesa em tempo real.
    Exibe todas as rodadas pedidas, status de preparo, itens agregados e botão de pedir a conta.
    """
    store = get_object_or_404(Store, slug=store_slug, is_active=True)
    table = get_object_or_404(Table, store=store, qr_token=qr_token, is_active=True)
    session = table.current_session

    orders = session.get_valid_orders() if session else []
    items_breakdown = session.get_items_breakdown() if session else []
    subtotal = session.calculate_subtotal() if session else Decimal('0.00')
    total = session.calculate_total() if session else Decimal('0.00')

    context = {
        'store': store,
        'table': table,
        'table_session': session,
        'orders': orders,
        'items_breakdown': items_breakdown,
        'subtotal': subtotal,
        'total': total,
        'current_year': timezone.localtime().year,
    }
    return render(request, 'orders/table_comanda.html', context)


