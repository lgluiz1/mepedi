from django.shortcuts import get_object_or_404, redirect
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from orders.models import Order
from stores.models import Store
from .services import (
    format_order_whatsapp_message,
    get_store_order_whatsapp_link,
    get_customer_whatsapp_link,
)


def order_whatsapp_redirect_view(request, store_slug, public_id):
    """
    Redireciona o usuário (cliente) diretamente para o WhatsApp oficial da loja
    com a mensagem do pedido devidamente estruturada.
    Rota: /<slug:store_slug>/pedidos/<uuid:public_id>/whatsapp/
    """
    store = get_object_or_404(Store, slug=store_slug, is_active=True)
    order = get_object_or_404(
        Order.objects.prefetch_related('items__selected_options', 'customer'),
        public_id=public_id,
        store=store
    )
    whatsapp_url = get_store_order_whatsapp_link(order, request=request)
    return redirect(whatsapp_url)


class OrderWhatsAppLinkAPIView(APIView):
    """
    Endpoint para obter a mensagem estruturada e os links dinâmicos do WhatsApp do pedido.
    GET /api/v1/whatsapp/orders/{public_id}/link/
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, public_id):
        order = get_object_or_404(
            Order.objects.prefetch_related('items__selected_options', 'customer'),
            public_id=public_id
        )
        
        public_url = request.build_absolute_uri(f"/{order.store.slug}/pedidos/{order.public_id}/")
        message = format_order_whatsapp_message(order, public_url=public_url)
        store_link = get_store_order_whatsapp_link(order, request=request)
        customer_link = get_customer_whatsapp_link(order)

        return Response({
            "order_id": order.id,
            "public_id": str(order.public_id),
            "order_number": order.order_number,
            "display_number": order.display_number,
            "formatted_message": message,
            "store_whatsapp_link": store_link,
            "customer_whatsapp_link": customer_link,
        })
