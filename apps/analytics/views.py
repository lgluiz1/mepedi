import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib import messages
from django.utils import timezone

from stores.models import Store
from orders.dashboard_views import get_user_active_store
from subscriptions.decorators import feature_required
from .models import TrackableLink, AnalyticsEvent
from .services import AnalyticsService
from .queries import parse_date_period, AnalyticsQueryService


from django.core.serializers.json import DjangoJSONEncoder
from django.utils.functional import Promise


class DecimalEncoder(DjangoJSONEncoder):
    """Auxiliar para serializar Decimal, Datetime e Strings Traduzidas (Promise) para JSON."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, Promise):
            return str(obj)
        return super().default(obj)


@login_required(login_url='/painel/login/')
@feature_required('analytics')
def merchant_analytics_view(request, store_slug):
    """
    Dashboard principal de Analytics e Inteligência para a loja selecionada.
    Multi-tenant validado: apenas lojistas autorizados podem visualizar.
    """
    current_store, active_stores = get_user_active_store(request.user, store_slug)

    # 1. Filtro de Período
    period = request.GET.get('period', '30d')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    active_tab = request.GET.get('tab', 'overview')

    start_dt, end_dt, period_label = parse_date_period(period, start_date_str, end_date_str)

    # 2. Executa agregações otimizadas
    query_service = AnalyticsQueryService(current_store, start_dt, end_dt, period_label)
    metrics = query_service.get_all_metrics()

    # 3. Serializa dados para gráficos do Chart.js
    chart_data = {
        'timeline': metrics['overview']['timeline'],
        'payment_stats': metrics['sales']['payment_stats'],
        'hourly_distribution': metrics['sales']['hourly_distribution'],
        'top_sources': metrics['traffic']['top_sources'],
        'funnel_steps': metrics['traffic']['funnel_steps'],
        'online_revenue': float(metrics['overview']['online_revenue']),
        'pdv_revenue': float(metrics['overview']['pdv_revenue']),
    }

    base_url = request.build_absolute_uri('/')[:-1]

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'active_nav': 'analytics',
        'active_tab': active_tab,
        'period': period,
        'period_label': period_label,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'metrics': metrics,
        'chart_data_json': json.dumps(chart_data, cls=DecimalEncoder),
        'base_url': base_url,
    }
    return render(request, 'dashboard/analytics.html', context)


@login_required(login_url='/painel/login/')
@feature_required('analytics')
def create_trackable_link_view(request, store_slug):
    """
    Criação de novos Links Rastreáveis com tags UTM personalizadas pelo lojista.
    """
    current_store, _ = get_user_active_store(request.user, store_slug)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        utm_source = request.POST.get('utm_source', '').strip()
        utm_campaign = request.POST.get('utm_campaign', '').strip()
        utm_medium = request.POST.get('utm_medium', 'social').strip()
        destination_path = request.POST.get('destination_path', '/').strip()

        if not name or not utm_source:
            messages.error(request, "Por favor, preencha o Nome do Link e a Origem (ex: instagram, whatsapp).")
        else:
            AnalyticsService.create_trackable_link(
                store=current_store,
                name=name,
                utm_source=utm_source,
                utm_campaign=utm_campaign,
                utm_medium=utm_medium,
                destination_path=destination_path
            )
            messages.success(request, f"Link '{name}' gerado com sucesso!")

    period = request.POST.get('period', '30d')
    return redirect(f"/painel/{store_slug}/analytics/?tab=traffic&period={period}")


@csrf_exempt
def track_event_api_view(request, store_slug):
    """
    API pública e leve para registro de eventos de funil no frontend
    (PAGE_VIEW, PRODUCT_VIEW, ADD_TO_CART, CHECKOUT_STARTED).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido'}, status=405)

    store = get_object_or_404(Store, slug=store_slug, is_active=True)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST.dict()

    event_type = data.get('event_type')
    product_id = data.get('product_id')
    metadata = data.get('metadata') or {}

    valid_events = [choice[0] for choice in AnalyticsEvent.EVENT_CHOICES]
    if event_type not in valid_events:
        return JsonResponse({'error': 'Tipo de evento inválido'}, status=400)

    session_id = AnalyticsService.get_session_id(request)

    product = None
    if product_id:
        from catalog.models import Product
        product = Product.objects.filter(id=product_id, store=store).first()

    event = AnalyticsService.record_event(
        store=store,
        session_id=session_id,
        event_type=event_type,
        product=product,
        metadata=metadata
    )

    return JsonResponse({'success': True, 'event_id': event.id if event else None})
