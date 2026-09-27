import json
import logging
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator

from stores.models import Store
from orders.models import Order
from catalog.models import Product
from customers.models import Customer
from .models import Plan, Feature, Subscription, PaymentGatewayConfig, PaymentHistory, WebhookEvent, AuditLog
from .services.subscription_service import SubscriptionService
from .services.trial_service import TrialService
from .services.audit_service import AuditService
from .gateways.mercadopago import MercadoPagoGateway

logger = logging.getLogger(__name__)


def saas_admin_required(view_func):
    """
    Decorator de segurança restritivo para o Painel Administrativo do SaaS MePedi.
    Exige autenticação e privilégios de administrador (is_staff ou is_superuser).
    """
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/painel/login/?next={request.path}")
        if not (request.user.is_staff or request.user.is_superuser):
            return render(request, 'saas_admin/forbidden.html', {
                'error_message': 'Acesso exclusivo para administradores da plataforma MePedi.'
            }, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped_view


@saas_admin_required
def saas_admin_dashboard_view(request):
    """
    Visão Geral / Dashboard Central do SaaS MePedi.
    Apresenta KPIs macro da plataforma, lojas recentes, faturas e auditoria.
    """
    now = timezone.now()
    start_of_month = timezone.datetime(now.year, now.month, 1, tzinfo=timezone.get_current_timezone())

    # 1. Contagens de Lojas e Assinaturas
    total_stores = Store.objects.count()
    active_paid_stores = Subscription.objects.filter(status=Subscription.STATUS_ACTIVE).count()
    trial_stores = Subscription.objects.filter(status=Subscription.STATUS_TRIAL).count()
    past_due_stores = Subscription.objects.filter(status=Subscription.STATUS_PAST_DUE).count()
    expired_stores = Subscription.objects.filter(status__in=[Subscription.STATUS_EXPIRED, Subscription.STATUS_CANCELLED]).count()

    # 2. Métricas Financeiras
    estimated_mrr = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE
    ).aggregate(total=Sum('plan__price'))['total'] or Decimal('0.00')

    month_revenue = PaymentHistory.objects.filter(
        status=PaymentHistory.STATUS_APPROVED,
        payment_date__gte=start_of_month
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # 3. Métricas Globais da Plataforma (GMV e Pedidos)
    total_orders_platform = Order.objects.count()
    total_sales_platform = Order.objects.exclude(
        status=Order.STATUS_CANCELLED
    ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')

    # 4. Listagens Recentes
    recent_stores = Store.objects.select_related('owner').prefetch_related(
        'subscriptions__plan'
    ).order_by('-created_at')[:8]

    recent_payments = PaymentHistory.objects.select_related(
        'subscription__store', 'subscription__plan'
    ).order_by('-created_at')[:8]

    recent_audits = AuditLog.objects.select_related(
        'user', 'store'
    ).order_by('-created_at')[:8]

    # Prepara assinaturas atuais para as lojas recentes
    for st in recent_stores:
        st.latest_sub = st.subscriptions.first()

    context = {
        'total_stores': total_stores,
        'active_paid_stores': active_paid_stores,
        'trial_stores': trial_stores,
        'past_due_stores': past_due_stores,
        'expired_stores': expired_stores,
        'estimated_mrr': estimated_mrr,
        'month_revenue': month_revenue,
        'total_orders_platform': total_orders_platform,
        'total_sales_platform': total_sales_platform,
        'recent_stores': recent_stores,
        'recent_payments': recent_payments,
        'recent_audits': recent_audits,
        'active_nav': 'dashboard',
    }

    return render(request, 'saas_admin/dashboard.html', context)


@saas_admin_required
def saas_admin_merchants_view(request):
    """
    Gestão Completa de Lojistas e Estabelecimentos.
    Filtros dinâmicos por status de assinatura, plano e busca textual.
    """
    status_filter = request.GET.get('status', 'all')
    plan_filter = request.GET.get('plan', 'all')
    search_query = request.GET.get('q', '').strip()

    qs = Store.objects.select_related('owner').prefetch_related('subscriptions__plan').order_by('-created_at')

    # Busca textual ampla (Nome da loja, Lojista, E-mail, WhatsApp, Documento)
    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query) |
            Q(owner__full_name__icontains=search_query) |
            Q(owner__email__icontains=search_query) |
            Q(whatsapp__icontains=search_query) |
            Q(document__icontains=search_query)
        )

    # Filtro por Status da Assinatura
    if status_filter == 'trial':
        qs = qs.filter(subscriptions__status=Subscription.STATUS_TRIAL)
    elif status_filter == 'active':
        qs = qs.filter(subscriptions__status=Subscription.STATUS_ACTIVE)
    elif status_filter == 'past_due':
        qs = qs.filter(subscriptions__status=Subscription.STATUS_PAST_DUE)
    elif status_filter == 'expired':
        qs = qs.filter(subscriptions__status=Subscription.STATUS_EXPIRED)
    elif status_filter == 'cancelled':
        qs = qs.filter(subscriptions__status=Subscription.STATUS_CANCELLED)

    # Filtro por Plano
    if plan_filter and plan_filter != 'all':
        qs = qs.filter(subscriptions__plan__slug=plan_filter)

    qs = qs.distinct()

    # Paginação (20 lojas por página)
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Enriquecimento com informações de assinatura para exibição
    for st in page_obj:
        sub = st.subscriptions.first()
        st.latest_sub = sub
        if sub and sub.status == Subscription.STATUS_TRIAL:
            st.trial_calc = TrialService.calculate_metrics(st, sub.trial_started_at)
        else:
            st.trial_calc = None

    plans = Plan.objects.filter(is_active=True).order_by('display_order')

    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'plan_filter': plan_filter,
        'search_query': search_query,
        'plans': plans,
        'active_nav': 'merchants',
    }

    return render(request, 'saas_admin/merchants.html', context)


@saas_admin_required
def saas_admin_store_detail_view(request, store_id):
    """
    Visão 360° do Estabelecimento no SaaS MePedi.
    Exibe dados contratuais, plano, histórico de faturas, consumo de recursos e botões de ação.
    """
    store = get_object_or_404(Store.objects.select_related('owner'), id=store_id)
    subscription = SubscriptionService.get_current_subscription(store)
    trial_info = TrialService.check_trial_status(store)

    # Operações e Estatísticas da Loja
    orders_count = Order.objects.filter(store=store).count()
    valid_revenue = Order.objects.filter(store=store).exclude(
        status=Order.STATUS_CANCELLED
    ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')

    products_count = Product.objects.filter(category__store=store).count()
    customers_count = Customer.objects.filter(store=store).count()

    # Histórico de Pagamentos e Auditoria
    payments = PaymentHistory.objects.filter(
        subscription__store=store
    ).select_related('subscription__plan').order_by('-created_at')[:20]

    audits = AuditLog.objects.filter(
        store=store
    ).select_related('user').order_by('-created_at')[:20]

    available_plans = Plan.objects.filter(is_active=True).order_by('display_order', 'price')

    context = {
        'store': store,
        'subscription': subscription,
        'trial_info': trial_info,
        'orders_count': orders_count,
        'valid_revenue': valid_revenue,
        'products_count': products_count,
        'customers_count': customers_count,
        'payments': payments,
        'audits': audits,
        'available_plans': available_plans,
        'active_nav': 'merchants',
    }

    return render(request, 'saas_admin/store_detail.html', context)


@saas_admin_required
@require_POST
def saas_admin_change_plan_view(request, store_id):
    """
    Ação Administrativa: Alteração Manual de Plano (Upgrade/Downgrade pelo Administrador).
    Registra a motivação na trilha de auditoria.
    """
    store = get_object_or_404(Store, id=store_id)
    plan_id = request.POST.get('plan_id')
    reason = request.POST.get('reason', '').strip()

    plan = get_object_or_404(Plan, id=plan_id)
    sub_before = SubscriptionService.get_current_subscription(store)
    old_plan_name = sub_before.plan.name if (sub_before and sub_before.plan) else "Sem Plano (Trial)"

    new_sub = SubscriptionService.activate_plan(store=store, plan=plan)

    AuditService.log(
        action=AuditLog.ACTION_PLAN_CHANGE,
        user=request.user,
        store=store,
        details={
            'old_plan': old_plan_name,
            'new_plan': plan.name,
            'plan_price': str(plan.price),
            'reason': reason or 'Alteração administrativa direta',
        },
        request=request
    )

    return redirect(f"/gestao-saas/lojas/{store.id}/?msg=plan_changed")


@saas_admin_required
@require_POST
def saas_admin_extend_trial_view(request, store_id):
    """
    Ação Administrativa: Extensão do Período de Testes (Trial).
    Adiciona dias extras ao prazo de avaliação com auditoria.
    """
    store = get_object_or_404(Store, id=store_id)
    days = int(request.POST.get('days', 30))
    reason = request.POST.get('reason', '').strip()

    sub = SubscriptionService.get_current_subscription(store)
    if not sub:
        sub = SubscriptionService.start_trial(store)

    base_end = sub.trial_ends_at or timezone.now()
    if base_end < timezone.now():
        base_end = timezone.now()

    sub.trial_ends_at = base_end + timezone.timedelta(days=days)
    sub.status = Subscription.STATUS_TRIAL
    sub.trial_expired_reason = None
    sub.save(update_fields=['status', 'trial_ends_at', 'trial_expired_reason', 'updated_at'])

    AuditService.log(
        action=AuditLog.ACTION_TRIAL_EXTEND,
        user=request.user,
        store=store,
        details={
            'added_days': days,
            'new_trial_ends_at': sub.trial_ends_at.strftime('%d/%m/%Y'),
            'reason': reason or 'Concessão de prazo de teste extra',
        },
        request=request
    )

    return redirect(f"/gestao-saas/lojas/{store.id}/?msg=trial_extended")


@saas_admin_required
@require_POST
def saas_admin_toggle_store_status_view(request, store_id):
    """
    Ação Administrativa: Suspender ou Reativar Loja no SaaS.
    """
    store = get_object_or_404(Store, id=store_id)
    action_type = request.POST.get('action_type')  # 'suspend' ou 'reactivate'
    reason = request.POST.get('reason', '').strip()

    sub = SubscriptionService.get_current_subscription(store)

    if action_type == 'suspend':
        store.is_active = False
        store.save(update_fields=['is_active', 'updated_at'])
        if sub:
            sub.status = Subscription.STATUS_SUSPENDED
            sub.save(update_fields=['status', 'updated_at'])

        AuditService.log(
            action=AuditLog.ACTION_STORE_SUSPEND,
            user=request.user,
            store=store,
            details={'reason': reason or 'Suspensão administrativa'},
            request=request
        )
    elif action_type == 'reactivate':
        store.is_active = True
        store.save(update_fields=['is_active', 'updated_at'])
        if sub:
            sub.status = Subscription.STATUS_ACTIVE if sub.plan else Subscription.STATUS_TRIAL
            sub.save(update_fields=['status', 'updated_at'])

        AuditService.log(
            action=AuditLog.ACTION_STORE_REACTIVATE,
            user=request.user,
            store=store,
            details={'reason': reason or 'Reativação administrativa'},
            request=request
        )

    return redirect(f"/gestao-saas/lojas/{store.id}/?msg=status_updated")


@saas_admin_required
@require_POST
def saas_admin_support_start_view(request, store_id):
    """
    Recurso de Governança: Inicia o "Modo Suporte".
    Permite que o administrador navegue temporariamente na experiência da loja para atendimento técnico.
    Exibe banner de alto destaque permanente e registra data, hora, IP e responsável na auditoria.
    """
    store = get_object_or_404(Store, id=store_id)

    # Configura chaves de sessão para o Modo Suporte
    request.session['support_mode_original_admin_id'] = request.user.id
    request.session['support_mode_store_id'] = store.id
    request.session['support_mode_store_name'] = store.name

    AuditService.log(
        action=AuditLog.ACTION_SUPPORT_START,
        user=request.user,
        store=store,
        details={'destination': f"/painel/{store.slug}/"},
        request=request
    )

    return redirect(f"/painel/{store.slug}/")


@saas_admin_required
def saas_admin_support_end_view(request):
    """
    Encerra o Modo Suporte e retorna o administrador ao painel central de gestão do SaaS.
    """
    store_id = request.session.get('support_mode_store_id')
    store = Store.objects.filter(id=store_id).first() if store_id else None

    AuditService.log(
        action=AuditLog.ACTION_SUPPORT_END,
        user=request.user,
        store=store,
        details={'session_cleared': True},
        request=request
    )

    # Limpa as chaves de sessão de suporte
    request.session.pop('support_mode_original_admin_id', None)
    request.session.pop('support_mode_store_id', None)
    request.session.pop('support_mode_store_name', None)

    if store:
        return redirect(f"/gestao-saas/lojas/{store.id}/?msg=support_ended")
    return redirect("/gestao-saas/lojistas/?msg=support_ended")


@saas_admin_required
def saas_admin_finance_view(request):
    """
    Módulo Financeiro do SaaS MePedi.
    Apresenta MRR, receitas por plano, pagamentos aprovados/pendentes e histórico de faturas.
    """
    now = timezone.now()
    start_of_month = timezone.datetime(now.year, now.month, 1, tzinfo=timezone.get_current_timezone())

    # MRR e Métricas do Mês
    mrr = Subscription.objects.filter(
        status=Subscription.STATUS_ACTIVE
    ).aggregate(total=Sum('plan__price'))['total'] or Decimal('0.00')

    month_revenue = PaymentHistory.objects.filter(
        status=PaymentHistory.STATUS_APPROVED,
        payment_date__gte=start_of_month
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_revenue_all_time = PaymentHistory.objects.filter(
        status=PaymentHistory.STATUS_APPROVED
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Contagens de Pagamentos
    approved_count = PaymentHistory.objects.filter(status=PaymentHistory.STATUS_APPROVED).count()
    pending_count = PaymentHistory.objects.filter(status=PaymentHistory.STATUS_PENDING).count()
    rejected_count = PaymentHistory.objects.filter(status=PaymentHistory.STATUS_REJECTED).count()

    # Receita por Plano
    revenue_by_plan = Plan.objects.annotate(
        active_subscriptions_count=Count('subscriptions', filter=Q(subscriptions__status=Subscription.STATUS_ACTIVE)),
        total_monthly_value=Sum('subscriptions__plan__price', filter=Q(subscriptions__status=Subscription.STATUS_ACTIVE))
    ).order_by('-total_monthly_value')

    # Histórico de Pagamentos com Paginação
    status_filter = request.GET.get('status', 'all')
    payments_qs = PaymentHistory.objects.select_related(
        'subscription__store', 'subscription__plan'
    ).order_by('-created_at')

    if status_filter != 'all':
        payments_qs = payments_qs.filter(status=status_filter.upper())

    paginator = Paginator(payments_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'mrr': mrr,
        'month_revenue': month_revenue,
        'total_revenue_all_time': total_revenue_all_time,
        'approved_count': approved_count,
        'pending_count': pending_count,
        'rejected_count': rejected_count,
        'revenue_by_plan': revenue_by_plan,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'active_nav': 'finance',
    }

    return render(request, 'saas_admin/finance.html', context)


@saas_admin_required
def saas_admin_gateways_view(request):
    """
    Configuração e Gestão de Gateways de Pagamento (Mercado Pago).
    Permite alternar credenciais (Sandbox/Produção) diretamente pelo painel administrativo.
    """
    mp_config, _ = PaymentGatewayConfig.objects.get_or_create(
        gateway=PaymentGatewayConfig.GATEWAY_MERCADOPAGO,
        defaults={
            'environment': PaymentGatewayConfig.ENV_SANDBOX,
            'is_active': True,
        }
    )

    if request.method == 'POST':
        environment = request.POST.get('environment', PaymentGatewayConfig.ENV_SANDBOX)
        access_token = request.POST.get('access_token', '').strip()
        public_key = request.POST.get('public_key', '').strip()
        webhook_secret = request.POST.get('webhook_secret', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        mp_config.environment = environment
        if access_token:
            mp_config.access_token = access_token
        if public_key:
            mp_config.public_key = public_key
        if webhook_secret:
            mp_config.webhook_secret = webhook_secret
        mp_config.is_active = is_active
        mp_config.save()

        AuditService.log(
            action=AuditLog.ACTION_GATEWAY_UPDATE,
            user=request.user,
            details={
                'gateway': 'MERCADOPAGO',
                'environment': environment,
                'is_active': is_active,
                'has_access_token': bool(mp_config.access_token),
            },
            request=request
        )

        return redirect('/gestao-saas/gateways/?msg=saved')

    context = {
        'mp_config': mp_config,
        'active_nav': 'gateways',
    }

    return render(request, 'saas_admin/gateways.html', context)


@saas_admin_required
@require_POST
def saas_admin_test_gateway_view(request):
    """
    Endpoint AJAX para testar em tempo real a conectividade e validade das credenciais do Gateway.
    """
    mp_config = PaymentGatewayConfig.objects.filter(
        gateway=PaymentGatewayConfig.GATEWAY_MERCADOPAGO
    ).first()

    gateway = MercadoPagoGateway(config=mp_config)
    is_valid = gateway.test_connection()

    if is_valid:
        return JsonResponse({
            'status': 'success',
            'message': 'Conexão estabelecida com sucesso com a API do Mercado Pago!'
        })
    else:
        return JsonResponse({
            'status': 'error',
            'message': 'Não foi possível validar as credenciais. Verifique o Access Token informado.'
        })


@saas_admin_required
def saas_admin_audit_view(request):
    """
    Trilha Completa de Auditoria de Ações Administrativas do SaaS MePedi.
    """
    action_filter = request.GET.get('action', 'all')
    search_query = request.GET.get('q', '').strip()

    qs = AuditLog.objects.select_related('user', 'store').order_by('-created_at')

    if action_filter != 'all':
        qs = qs.filter(action=action_filter)

    if search_query:
        qs = qs.filter(
            Q(store__name__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(ip_address__icontains=search_query)
        )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    actions_choices = AuditLog.ACTION_CHOICES

    context = {
        'page_obj': page_obj,
        'action_filter': action_filter,
        'search_query': search_query,
        'actions_choices': actions_choices,
        'active_nav': 'audit',
    }

    return render(request, 'saas_admin/audit.html', context)
