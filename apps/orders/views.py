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
from .models import Order, Coupon
from .services import OrderService
from .serializers import (
    OrderDetailSerializer,
    CreateOrderRequestSerializer,
    UpdateOrderStatusSerializer
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

