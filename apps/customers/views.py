from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound
from django.shortcuts import get_object_or_404
from django.db import transaction

from stores.models import Store
from .models import Customer, CustomerAddress, clean_phone_number
from .serializers import (
    CustomerSerializer,
    CustomerAddressSerializer,
    CustomerIdentifyRequestSerializer
)


class IsStoreMember(permissions.BasePermission):
    message = "Você não possui permissão para acessar os clientes desta loja."

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


class MerchantCustomerListView(generics.ListAPIView):
    """
    Lista de clientes pertencentes à loja do lojista com busca por nome ou telefone.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = CustomerSerializer

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        get_user_store(self.request.user, store_id)
        qs = Customer.objects.filter(store_id=store_id).prefetch_related('addresses')
        search = self.request.query_params.get('search')
        if search:
            clean_search = clean_phone_number(search)
            if clean_search:
                qs = qs.filter(phone__contains=clean_search)
            else:
                qs = qs.filter(name__icontains=search)
        return qs


class MerchantCustomerDetailView(generics.RetrieveUpdateAPIView):
    """
    Detalhes e atualização de anotações do cliente pelo lojista.
    """
    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = CustomerSerializer
    lookup_field = 'id'

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        get_user_store(self.request.user, store_id)
        return Customer.objects.filter(store_id=store_id).prefetch_related('addresses')


class PublicCustomerIdentifyView(APIView):
    """
    Endpoint público de identificação rápida no cardápio / checkout:
    POST /api/v1/customers/public/{store_slug}/identify/
    - Recebe telefone (obrigatório), nome (obrigatório) e CPF (opcional).
    - Se o cliente já existir naquela loja: recupera o cadastro e seus endereços salvos.
    - Se não existir: cadastra o novo cliente na loja.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request, store_slug):
        store = get_object_or_404(Store, slug=store_slug, is_active=True)
        serializer = CustomerIdentifyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        name = serializer.validated_data['name']
        document = serializer.validated_data.get('document', '')
        email = serializer.validated_data.get('email', '')

        customer, created = Customer.objects.get_or_create(
            store=store,
            phone=phone,
            defaults={
                'name': name,
                'document': document,
                'email': email
            }
        )

        # Se já existia, atualiza dados se enviados
        if not created:
            updated = False
            if name and customer.name != name:
                customer.name = name
                updated = True
            if document and not customer.document:
                customer.document = document
                updated = True
            if email and not customer.email:
                customer.email = email
                updated = True
            if updated:
                customer.save()

        return Response({
            "created": created,
            "customer": CustomerSerializer(customer).data
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class PublicCustomerLookupView(APIView):
    """
    Busca rápida de cliente pelo telefone na loja para auto-preenchimento no checkout.
    GET /api/v1/customers/public/{store_slug}/lookup/?phone=11988887777
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, store_slug):
        store = get_object_or_404(Store, slug=store_slug, is_active=True)
        phone_raw = request.query_params.get('phone', '').strip()
        clean_phone = clean_phone_number(phone_raw)

        if not clean_phone or len(clean_phone) < 8:
            return Response({"found": False, "message": "Telefone inválido."}, status=status.HTTP_400_BAD_REQUEST)

        phone_variations = [clean_phone]
        if clean_phone.startswith('55') and len(clean_phone) in (12, 13):
            phone_variations.append(clean_phone[2:])
        else:
            phone_variations.append(f"55{clean_phone}")

        customer = Customer.objects.filter(store=store, phone__in=phone_variations).prefetch_related('addresses').first()
        if not customer:
            return Response({"found": False})

        return Response({
            "found": True,
            "customer": CustomerSerializer(customer).data
        })

