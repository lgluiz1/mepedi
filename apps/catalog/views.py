from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from django.shortcuts import get_object_or_404
from django.db.models import Prefetch

from stores.models import Store
from stores.serializers import StorePublicSerializer
from .models import Category, Product, OptionGroup, OptionItem
from .serializers import (
    CategorySerializer,
    ProductSerializer,
    OptionGroupSerializer,
    OptionItemSerializer,
    PublicCategoryMenuSerializer
)


class IsStoreMember(permissions.BasePermission):
    """
    Valida se o usuário autenticado possui vínculo ativo com a loja informada na URL.
    Retorna 403 Forbidden caso o usuário não pertença à loja.
    """
    message = "Você não possui permissão para gerenciar os dados desta loja."

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
    """
    Função auxiliar para validar e recuperar a loja do lojista autenticado.
    Garante o isolamento multi-loja.
    """
    try:
        return Store.objects.get(
            id=store_id,
            memberships__user=user,
            memberships__is_active=True
        )
    except Store.DoesNotExist:
        raise PermissionDenied("Você não possui permissão para gerenciar esta loja.")


# =====================================================================
# Endpoints do Lojista: Categorias
# =====================================================================

class MerchantCategoryListCreateView(generics.ListCreateAPIView):
    """
    Listar e criar categorias para uma loja do lojista.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = CategorySerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['store'] = get_user_store(self.request.user, self.kwargs.get('store_id'))
        return context

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return Category.objects.filter(store_id=store_id)

    def perform_create(self, serializer):
        store_id = self.kwargs.get('store_id')
        store = get_user_store(self.request.user, store_id)
        serializer.save(store=store)


class MerchantCategoryDetailUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    """
    Visualizar, atualizar ou excluir uma categoria com garantia de tenancy.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = CategorySerializer
    lookup_field = 'id'

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['store'] = get_user_store(self.request.user, self.kwargs.get('store_id'))
        return context

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return Category.objects.filter(store_id=store_id)


# =====================================================================
# Endpoints do Lojista: Produtos
# =====================================================================

class MerchantProductListCreateView(generics.ListCreateAPIView):
    """
    Listar e cadastrar novos produtos para a loja.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = ProductSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['store'] = get_user_store(self.request.user, self.kwargs.get('store_id'))
        return context

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        category_id = self.request.query_params.get('category_id')
        qs = Product.objects.filter(store_id=store_id).select_related('category').prefetch_related('option_groups__items')
        if category_id:
            qs = qs.filter(category_id=category_id)
        return qs

    def perform_create(self, serializer):
        store_id = self.kwargs.get('store_id')
        store = get_user_store(self.request.user, store_id)
        serializer.save(store=store)


class MerchantProductDetailUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    """
    Visualizar, atualizar ou deletar produto da loja.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = ProductSerializer
    lookup_field = 'id'

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['store'] = get_user_store(self.request.user, self.kwargs.get('store_id'))
        return context

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return Product.objects.filter(store_id=store_id).select_related('category').prefetch_related('option_groups__items')


# =====================================================================
# Endpoints do Lojista: Grupos de Opções
# =====================================================================

class MerchantOptionGroupListCreateView(generics.ListCreateAPIView):
    """
    Listar e criar grupos de opções para um produto da loja.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = OptionGroupSerializer

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        product_id = self.kwargs.get('product_id')
        return OptionGroup.objects.filter(store_id=store_id, product_id=product_id).prefetch_related('items')

    def perform_create(self, serializer):
        store_id = self.kwargs.get('store_id')
        product_id = self.kwargs.get('product_id')
        store = get_user_store(self.request.user, store_id)
        product = get_object_or_404(Product, id=product_id, store=store)
        serializer.save(store=store, product=product)


class MerchantOptionGroupDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = OptionGroupSerializer
    lookup_field = 'id'

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return OptionGroup.objects.filter(store_id=store_id).prefetch_related('items')


# =====================================================================
# Endpoints do Lojista: Itens de Opção (Adicionais / Remoções)
# =====================================================================

class MerchantOptionItemListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = OptionItemSerializer

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        group_id = self.kwargs.get('group_id')
        return OptionItem.objects.filter(option_group_id=group_id, option_group__store_id=store_id)

    def perform_create(self, serializer):
        store_id = self.kwargs.get('store_id')
        group_id = self.kwargs.get('group_id')
        store = get_user_store(self.request.user, store_id)
        option_group = get_object_or_404(OptionGroup, id=group_id, store=store)
        serializer.save(option_group=option_group)


class MerchantOptionItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = OptionItemSerializer
    lookup_field = 'id'

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        return OptionItem.objects.filter(option_group__store_id=store_id)


# =====================================================================
# Endpoint Público: Cardápio Completo da Loja por Slug
# =====================================================================

class PublicStoreMenuView(APIView):
    """
    Retorna o cardápio público completo de uma loja a partir do seu slug.
    Otimizado para o consumo mobile-first com apenas 1 requisição.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        store = get_object_or_404(Store, slug=slug, is_active=True)

        # Pré-carrega categorias ativas com produtos ativos e seus adicionais
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

        return Response({
            "store": StorePublicSerializer(store).data,
            "categories": PublicCategoryMenuSerializer(categories, many=True).data
        })
