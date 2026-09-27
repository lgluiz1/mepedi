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
    authentication_classes = []
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
        from django.utils import timezone
        store = get_user_store(request.user, store_id)
        if 'is_open' in request.data:
            new_is_open = bool(request.data['is_open'])
            store.is_open = new_is_open
            if new_is_open:
                if not store.opened_at:
                    store.opened_at = timezone.now()
            else:
                store.opened_at = None

        if 'is_paused' in request.data:
            store.is_paused = bool(request.data['is_paused'])

        store.save()
        return Response({
            "is_open": store.is_open,
            "is_paused": store.is_paused,
            "is_currently_open": store.is_currently_open(),
            "status_label": store.status_label,
            "open_duration_minutes": store.get_open_duration_minutes(),
            "today_hours": store.get_today_hours_display(),
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


def public_store_menu_view(request, store_slug):
    """
    Página pública do cardápio digital do lojista (mobile-first).
    Carrega loja, categorias, produtos com fotos e opções, horários e zonas de frete.
    """
    import json
    from django.shortcuts import render
    from django.db.models import Prefetch
    from catalog.models import Category, Product, OptionGroup, OptionItem
    from delivery.models import DeliveryZone

    store = get_object_or_404(
        Store.objects.prefetch_related('business_hours'),
        slug=store_slug,
        is_active=True
    )

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

    delivery_zones = DeliveryZone.objects.filter(store=store, is_active=True)
    is_open = store.is_currently_open()
    status_label = store.status_label

    # Prepara catálogo em JSON para o carrinho reativo no frontend
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

    # Cupons públicos ativos para anúncio no topo do cardápio
    from orders.models import Coupon
    from django.db.models import Q
    from django.utils import timezone
    now = timezone.now()
    public_coupons = Coupon.objects.filter(
        store=store,
        is_active=True,
        is_public=True
    ).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=now)
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=now)
    ).order_by('-discount_value')

    weekdays_schedule = store.business_hours.all().order_by('weekday')
    today_hours = store.get_today_hours_display()

    next_opening_text = store.get_next_opening_text()

    context = {
        'store': store,
        'categories': categories,
        'delivery_zones': delivery_zones,
        'is_open': is_open,
        'status_label': status_label,
        'today_hours': today_hours,
        'next_opening_text': next_opening_text,
        'weekdays_schedule': weekdays_schedule,
        'public_coupons': public_coupons,
        'products_catalog_json': json.dumps(products_catalog),
        'current_year': timezone.localtime().year,
    }
    # Registro silencioso e não-intrusivo de visita para Analytics
    try:
        from analytics.services import AnalyticsService
        AnalyticsService.record_visit(request, store)
    except Exception:
        pass

    return render(request, 'stores/public_menu.html', context)
