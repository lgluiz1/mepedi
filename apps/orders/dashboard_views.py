from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from stores.models import Store
from .models import Order


def merchant_login_view(request):
    """
    Tela de login exclusiva para o painel de pedidos do lojista.
    """
    if request.user.is_authenticated:
        return redirect('merchant_dashboard_root')

    error = None
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        if not email or not password:
            error = "Por favor, preencha o e-mail e a senha."
        else:
            user = authenticate(request, username=email, password=password)
            if user:
                login(request, user)
                next_url = request.GET.get('next', '/painel/')
                return redirect(next_url)
            else:
                error = "E-mail ou senha inválidos. Tente novamente."

    return render(request, 'dashboard/login.html', {'error': error})


def merchant_logout_view(request):
    """
    Encerra a sessão do lojista e redireciona para a tela de login.
    """
    logout(request)
    return redirect('merchant_login')


@login_required(login_url='/painel/login/')
def merchant_dashboard_root_view(request):
    """
    Ponto de entrada do painel: redireciona para a primeira loja do lojista.
    """
    user_memberships = request.user.memberships.filter(is_active=True).select_related('store')
    active_stores = [m.store for m in user_memberships if m.store.is_active]

    if not active_stores:
        return render(request, 'dashboard/no_store.html')

    return redirect('merchant_dashboard_store', store_slug=active_stores[0].slug)


@login_required(login_url='/painel/login/')
def merchant_dashboard_store_view(request, store_slug):
    """
    Painel de controle e acompanhamento de pedidos em tempo real para a loja selecionada.
    """
    user_memberships = request.user.memberships.filter(is_active=True).select_related('store')
    active_stores = [m.store for m in user_memberships if m.store.is_active]

    # Encontra a loja selecionada garantindo multi-tenancy
    current_store = next((s for s in active_stores if s.slug == store_slug), None)
    if not current_store:
        raise PermissionDenied("Você não possui permissão para acessar esta loja.")

    orders_qs = Order.objects.filter(store=current_store).prefetch_related(
        'items__selected_options', 'customer'
    ).order_by('-created_at')

    today = timezone.localdate()
    today_orders = orders_qs.filter(created_at__date=today)
    today_revenue = sum(
        (o.total for o in today_orders if o.status != 'CANCELADO'),
        Decimal('0.00')
    )

    counts = {
        'ALL': orders_qs.count(),
        'NOVO': orders_qs.filter(status='NOVO').count(),
        'ACEITO': orders_qs.filter(status='ACEITO').count(),
        'EM_PREPARACAO': orders_qs.filter(status='EM_PREPARACAO').count(),
        'PRONTO': orders_qs.filter(status='PRONTO').count(),
        'SAIU_PARA_ENTREGA': orders_qs.filter(status='SAIU_PARA_ENTREGA').count(),
        'CONCLUIDO': orders_qs.filter(status='CONCLUIDO').count(),
        'CANCELADO': orders_qs.filter(status='CANCELADO').count(),
    }

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'orders': orders_qs[:100],
        'counts': counts,
        'today_orders_count': today_orders.count(),
        'today_revenue': today_revenue,
        'is_currently_open': current_store.is_currently_open(),
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'dashboard/orders.html', context)
