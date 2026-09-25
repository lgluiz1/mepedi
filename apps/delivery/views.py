from decimal import Decimal
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound
from django.shortcuts import get_object_or_404

from stores.models import Store
from .models import DeliveryZone
from .serializers import DeliveryZoneSerializer, CalculateFeeRequestSerializer


class IsStoreMember(permissions.BasePermission):
    message = "Você não possui permissão para gerenciar a entrega desta loja."

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
        raise PermissionDenied("Você não possui permissão para gerenciar esta loja.")


class MerchantDeliveryZoneListCreateView(generics.ListCreateAPIView):
    """
    Listar e criar regiões/zonas de entrega para a loja.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = DeliveryZoneSerializer

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return DeliveryZone.objects.filter(store_id=store_id)

    def perform_create(self, serializer):
        store_id = self.kwargs.get('store_id')
        store = get_user_store(self.request.user, store_id)
        serializer.save(store=store)


class MerchantDeliveryZoneDetailUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    """
    Visualizar, atualizar ou excluir uma região de entrega.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = DeliveryZoneSerializer
    lookup_field = 'id'

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return DeliveryZone.objects.filter(store_id=store_id)


class PublicDeliveryZoneListView(generics.ListAPIView):
    """
    Endpoint público: retorna as regiões e taxas ativas de uma loja pelo slug.
    Ex: /api/v1/delivery/public/{store_slug}/zones/
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = DeliveryZoneSerializer

    def get_queryset(self):
        store_slug = self.kwargs.get('store_slug')
        store = get_object_or_404(Store, slug=store_slug, is_active=True)
        return DeliveryZone.objects.filter(store=store, is_active=True)


class PublicCalculateDeliveryFeeView(APIView):
    """
    Calcula a taxa de entrega da loja para um bairro informado.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, store_slug):
        store = get_object_or_404(Store, slug=store_slug, is_active=True)
        serializer = CalculateFeeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        neighborhood = serializer.validated_data.get('neighborhood', '').strip()

        # 1. Se a loja possui taxa fixa de entrega positiva configurada:
        if store.fixed_delivery_fee and store.fixed_delivery_fee > Decimal('0.00'):
            return Response({
                "matched": True,
                "zone_id": None,
                "zone_name": "Taxa Fixa de Entrega",
                "delivery_fee": str(store.fixed_delivery_fee),
                "estimated_time_min": store.estimated_delivery_time_min,
                "estimated_time_max": store.estimated_delivery_time_max
            })

        # 2. Procura nas zonas ativas da loja se alguma atende este bairro
        zones = DeliveryZone.objects.filter(store=store, is_active=True)
        matched_zone = None
        for zone in zones:
            if zone.match_neighborhood(neighborhood):
                matched_zone = zone
                break

        if matched_zone:
            return Response({
                "matched": True,
                "zone_id": matched_zone.id,
                "zone_name": matched_zone.name,
                "delivery_fee": str(matched_zone.fee),
                "estimated_time_min": matched_zone.estimated_time_min,
                "estimated_time_max": matched_zone.estimated_time_max
            })

        # 3. Se não houver zona específica encontrada, retorna a primeira zona geral ou informa indisponível
        default_zone = zones.first()
        if default_zone:
            return Response({
                "matched": False,
                "zone_id": default_zone.id,
                "zone_name": f"{default_zone.name} (Padrão)",
                "delivery_fee": str(default_zone.fee),
                "estimated_time_min": default_zone.estimated_time_min,
                "estimated_time_max": default_zone.estimated_time_max
            })

        # 4. Se a loja não possui zonas cadastradas e fixed_delivery_fee é 0.00, entrega grátis!
        if store.allows_delivery:
            return Response({
                "matched": True,
                "zone_id": None,
                "zone_name": "Entrega Grátis",
                "delivery_fee": "0.00",
                "estimated_time_min": store.estimated_delivery_time_min,
                "estimated_time_max": store.estimated_delivery_time_max
            })

        return Response({
            "matched": False,
            "message": "Nenhuma região de entrega configurada para este estabelecimento."
        }, status=status.HTTP_404_NOT_FOUND)
