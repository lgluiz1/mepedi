from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .models import Store
from .serializers import StoreDetailSerializer, StorePublicSerializer


class StorePublicDetailView(generics.RetrieveAPIView):
    """
    Endpoint público do cardápio digital: recupera dados da loja pelo slug.
    Ex: /api/v1/stores/public/{slug}/
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = StorePublicSerializer
    lookup_field = 'slug'
    queryset = Store.objects.filter(is_active=True)


class MerchantStoreListCreateView(generics.ListCreateAPIView):
    """
    Endpoint do lojista para listar suas lojas e criar novas lojas adicionais.
    Garante que o lojista só veja as lojas vinculadas à sua conta.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StoreDetailSerializer

    def get_queryset(self):
        # Isolamento de multi-tenancy: somente lojas onde o usuário tem vínculo ativo
        user = self.request.user
        return Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True
        ).distinct()

    def perform_create(self, serializer):
        from accounts.models import StoreMembership
        # Salva a loja com o usuário como owner e cria a membership
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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StoreDetailSerializer
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        return Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True
        ).distinct()
