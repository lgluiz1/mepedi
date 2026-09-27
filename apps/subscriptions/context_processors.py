from stores.models import Store
from .models import Subscription
from .services.trial_service import TrialService
from .services.feature_service import FeatureService
from .services.subscription_service import SubscriptionService


def subscription_context(request):
    """
    Context processor global do SaaS MePedi.
    Injeta informações do plano, trial e funcionalidades liberadas para templates do lojista.
    """
    context = {}

    try:
        # Tenta resolver a loja a partir da URL ou do request
        store = None
        if hasattr(request, 'resolver_match') and request.resolver_match:
            store_slug = request.resolver_match.kwargs.get('store_slug')
            if store_slug:
                store = Store.objects.filter(slug=store_slug).first()

        if not store and hasattr(request, 'store') and request.store:
            store = request.store

        if not store and request.user.is_authenticated and hasattr(request.user, 'memberships'):
            # Se for lojista autenticado no painel, busca a loja ativa principal
            membership = request.user.memberships.filter(is_active=True).select_related('store').first()
            if membership:
                store = membership.store

        if store:
            sub = SubscriptionService.get_current_subscription(store)
            trial_info = TrialService.check_trial_status(store)
            accessible_features = FeatureService.get_accessible_features(store)

            context['saas_subscription'] = sub
            context['current_subscription'] = sub
            context['saas_trial_info'] = trial_info
            context['trial_info'] = trial_info
            context['saas_plan'] = sub.plan if (sub and sub.status == Subscription.STATUS_ACTIVE) else None
            context['active_plan'] = sub.plan if (sub and sub.status == Subscription.STATUS_ACTIVE) else None
            context['saas_features'] = accessible_features
            context['accessible_features'] = accessible_features

        # Verifica se o administrador está conectado em Modo Suporte
        if hasattr(request, 'session') and request.session.get('support_mode_store_id'):
            context['is_support_mode'] = True
            context['support_mode_store_id'] = request.session.get('support_mode_store_id')
            context['support_mode_store_name'] = request.session.get('support_mode_store_name')
            context['support_mode_admin_id'] = request.session.get('support_mode_original_admin_id')

    except Exception:
        # Falha silenciosa para nunca quebrar a renderização de páginas
        pass

    return context
