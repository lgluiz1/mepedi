from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .models import Store, BusinessHour
from .serializers import StoreDetailSerializer, StorePublicSerializer, BusinessHourSerializer


class IsStoreMember(permissions.BasePermission):
    message = "Você não possui permissão para gerenciar os dados desta loja."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        store_id = view.kwargs.get('store_id') or view.kwargs.get('id')
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


class StorePublicDetailView(generics.RetrieveAPIView):
    """
    Endpoint público do cardápio digital: recupera dados da loja pelo slug.
    Ex: /api/v1/stores/public/{slug}/
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = StorePublicSerializer
    lookup_field = 'slug'
    queryset = Store.objects.filter(is_active=True).prefetch_related('business_hours')


class MerchantStoreListCreateView(generics.ListCreateAPIView):
    """
    Endpoint do lojista para listar suas lojas e criar novas lojas adicionais.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StoreDetailSerializer

    def get_queryset(self):
        user = self.request.user
        return Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True
        ).distinct().prefetch_related('business_hours')

    def perform_create(self, serializer):
        from accounts.models import StoreMembership
        store = serializer.save(owner=self.request.user)
        StoreMembership.objects.create(
            user=self.request.user,
            store=store,
            role=StoreMembership.ROLE_OWNER,
            is_active=True
        )


class MerchantStoreDetailUpdateView(generics.RetrieveUpdateAPIView):
    """
    Endpoint do lojista para visualizar e atualizar dados da sua loja.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = StoreDetailSerializer
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        return Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True
        ).distinct().prefetch_related('business_hours')


class MerchantStoreToggleStatusView(APIView):
    """
    Endpoint rápido para o lojista abrir/fechar ou pausar/retomar pedidos.
    Ex: PATCH /api/v1/stores/merchant/{store_id}/toggle-status/
    Body: {"is_open": true} ou {"is_paused": true}
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]

    def patch(self, request, store_id):
        store = get_user_store(request.user, store_id)
        if 'is_open' in request.data:
            store.is_open = bool(request.data['is_open'])
        if 'is_paused' in request.data:
            store.is_paused = bool(request.data['is_paused'])
        store.save()
        return Response({
            "is_open": store.is_open,
            "is_paused": store.is_paused,
            "is_currently_open": store.is_currently_open(),
            "status_label": store.status_label
        })


class MerchantBusinessHourListCreateView(generics.ListCreateAPIView):
    """
    Listar e configurar horários de funcionamento da loja por dia da semana.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = BusinessHourSerializer

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return BusinessHour.objects.filter(store_id=store_id)

    def perform_create(self, serializer):
        store_id = self.kwargs.get('store_id')
        store = get_user_store(self.request.user, store_id)
        serializer.save(store=store)


class MerchantBusinessHourDetailUpdateView(generics.RetrieveUpdateDestroyAPIView):
    """
    Atualizar ou excluir um horário específico de dia da semana.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = BusinessHourSerializer
    lookup_field = 'id'

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return BusinessHour.objects.filter(store_id=store_id)
