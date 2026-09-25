from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from django.shortcuts import get_object_or_404, render
from django.core.exceptions import ValidationError as DjangoValidationError

from stores.models import Store
from .models import Order
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
                order_notes=data.get('notes', '')
            )
        except DjangoValidationError as e:
            msg = e.messages if hasattr(e, 'messages') else [str(e)]
            return Response({"error": msg[0] if msg else str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            OrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED
        )


class PublicOrderDetailView(generics.RetrieveAPIView):
    """
    Consulta pública do status do pedido pelo UUID público.
    GET /api/v1/orders/public/{public_id}/
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = OrderDetailSerializer
    lookup_field = 'public_id'
    queryset = Order.objects.all().prefetch_related('items__selected_options', 'customer')


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

        # Auto-cancela pedidos pendentes que não foram aceitos em até 10 minutos
        cutoff_10m = timezone.now() - datetime.timedelta(minutes=10)
        Order.objects.filter(store_id=store_id, status=Order.STATUS_NEW, created_at__lt=cutoff_10m).update(
            status=Order.STATUS_CANCELLED
        )

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

        order.status = new_status
        order.save(update_fields=update_fields)

        return Response(OrderDetailSerializer(order, context={'request': request}).data)


# =====================================================================
# Views de Template Django (Checkout e Acompanhamento)
# =====================================================================

def public_checkout_page(request, store_slug):
    """
    Renderiza a tela de checkout mobile-first da loja.
    """
    store = get_object_or_404(Store, slug=store_slug, is_active=True)
    delivery_zones = store.delivery_zones.filter(is_active=True) if hasattr(store, 'delivery_zones') else []

    context = {
        'store': store,
        'delivery_zones': delivery_zones,
        'is_open': store.is_currently_open(),
    }
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

