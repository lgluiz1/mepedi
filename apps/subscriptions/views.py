import json
import logging
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone

from orders.dashboard_views import get_user_active_store
from .models import Plan, Subscription, PaymentHistory
from .services.subscription_service import SubscriptionService
from .services.trial_service import TrialService
from .services.payment_service import PaymentService

logger = logging.getLogger(__name__)


@login_required(login_url='/painel/login/')
def merchant_subscription_view(request, store_slug):
    """
    Página 'Minha Assinatura' no Painel do Lojista.
    Apresenta:
    1. Status atual da loja (Trial com métricas em tempo real, ou Plano Comercial Ativo);
    2. Vitrine e comparativo comercial dos planos (Start, Pro, Gestão);
    3. Histórico de faturas e pagamentos com status;
    4. Garantia explícita: Planos comerciais pagos possuem pedidos e faturamento ILIMITADOS.
    """
    current_store, user_stores = get_user_active_store(request.user, store_slug)

    # 1. Recupera assinatura atual e métricas de trial
    subscription = SubscriptionService.get_current_subscription(current_store)
    trial_info = TrialService.check_trial_status(current_store)

    # Cálculos percentuais para barras de progresso
    days_used = trial_info.get('days_used', 0)
    orders_count = trial_info.get('orders_count', 0)
    revenue_total = trial_info.get('revenue_total', Decimal('0.00'))

    days_pct = min(100, int((days_used / 30.0) * 100)) if days_used else 0
    orders_pct = min(100, int((orders_count / 300.0) * 100)) if orders_count else 0
    revenue_pct = min(100, int((float(revenue_total) / 2000.0) * 100)) if revenue_total else 0

    # 2. Planos comerciais ativos para contratação/upgrade
    plans = Plan.objects.filter(is_active=True).prefetch_related('features').order_by('display_order', 'price')

    # 3. Histórico de faturas e transações
    payments = PaymentHistory.objects.filter(
        subscription__store=current_store
    ).select_related('subscription__plan').order_by('-created_at')[:30]

    # Feedback de redirecionamento do checkout
    feedback_status = request.GET.get('status')
    feedback_plan = request.GET.get('plan')
    highlight_slug = request.GET.get('highlight', '')

    context = {
        'store': current_store,
        'user_stores': user_stores,
        'current_subscription': subscription,
        'trial_info': trial_info,
        'days_pct': days_pct,
        'orders_pct': orders_pct,
        'revenue_pct': revenue_pct,
        'plans': plans,
        'payments': payments,
        'feedback_status': feedback_status,
        'feedback_plan': feedback_plan,
        'highlight_slug': highlight_slug,
        'active_tab': 'subscription',
    }

    return render(request, 'dashboard/subscription.html', context)


@login_required(login_url='/painel/login/')
def merchant_subscription_checkout_view(request, store_slug, plan_slug):
    """
    Inicia o fluxo de contratação ou upgrade de plano.
    Gera a preferência de checkout no Mercado Pago e redireciona o lojista para pagamento seguro.
    Suporta tanto requisições padrão (POST / GET) quanto requisições AJAX com resposta JSON.
    """
    current_store, _ = get_user_active_store(request.user, store_slug)
    plan = get_object_or_404(Plan, slug=plan_slug, is_active=True)

    payment_service = PaymentService('MERCADOPAGO')
    checkout_data = payment_service.create_subscription_checkout(
        store=current_store,
        plan=plan,
        user=request.user,
        request=request
    )

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
    if is_ajax:
        return JsonResponse({
            'status': 'success',
            'checkout_url': checkout_data['checkout_url'],
            'preference_id': checkout_data.get('preference_id'),
            'payment_history_id': checkout_data.get('payment_history_id'),
        })

    return redirect(checkout_data['checkout_url'])


@login_required(login_url='/painel/login/')
def merchant_subscription_return_view(request, store_slug):
    """
    Endpoint de retorno após o lojista concluir ou cancelar a transação no Mercado Pago.
    Captura os parâmetros do gateway, atualiza o status preliminar e redireciona para a tela de assinatura com feedback visual.
    """
    current_store, _ = get_user_active_store(request.user, store_slug)

    status = request.GET.get('status', '').lower()
    collection_status = request.GET.get('collection_status', '').lower()
    payment_id = request.GET.get('payment_id')
    plan_slug = request.GET.get('plan')

    is_approved = collection_status == 'approved' or status in ['success', 'approved']
    is_pending = collection_status == 'pending' or status == 'pending'

    if is_approved:
        if payment_id:
            pay = PaymentHistory.objects.filter(id=payment_id, subscription__store=current_store).first()
            if pay:
                pay.status = PaymentHistory.STATUS_APPROVED
                pay.payment_date = timezone.now()
                pay.save(update_fields=['status', 'payment_date', 'updated_at'])

        if plan_slug:
            plan = Plan.objects.filter(slug=plan_slug, is_active=True).first()
            if plan:
                SubscriptionService.activate_plan(store=current_store, plan=plan)

        return redirect(f"/painel/{current_store.slug}/assinatura/?status=success&plan={plan_slug or ''}")

    elif is_pending:
        return redirect(f"/painel/{current_store.slug}/assinatura/?status=pending&plan={plan_slug or ''}")

    else:
        return redirect(f"/painel/{current_store.slug}/assinatura/?status=failure&plan={plan_slug or ''}")


@csrf_exempt
@require_POST
def gateway_webhook_view(request, gateway):
    """
    Endpoint base para recebimento de webhooks de pagamento (ex: mercadopago, asaas).
    Garante idempotência e resposta HTTP 200 rápida.
    """
    gateway_name = gateway.upper()
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        logger.warning(f"Invalid JSON received on webhook for gateway {gateway_name}: {e}")
        return HttpResponseBadRequest("Invalid payload")

    # Extração de identificador conforme gateway
    data_obj = payload.get('data') or {}
    external_id = str(data_obj.get('id') or payload.get('id') or '')
    event_type = str(payload.get('type') or payload.get('action') or payload.get('topic') or '')

    if not external_id:
        return JsonResponse({'status': 'ignored', 'reason': 'missing_id'}, status=200)

    payment_service = PaymentService(gateway_name)
    result = payment_service.process_webhook_event(
        gateway=gateway_name,
        external_id=external_id,
        event_type=event_type,
        payload=payload
    )

    return JsonResponse(result, status=200)
