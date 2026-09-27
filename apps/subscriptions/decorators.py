from functools import wraps
from django.shortcuts import render
from django.http import JsonResponse
from stores.models import Store
from .services.feature_service import FeatureService
from .services.trial_service import TrialService
from .models import Feature, Plan, Subscription


def feature_required(feature_code: str):
    """
    Decorator que protege rotas do lojista exigindo permissão da funcionalidade (Feature).

    Comportamento:
    - Se a loja tem acesso à feature (via Trial ativo ou Plano Contratado): permite execução.
    - Se a loja NÃO tem acesso ou se o Trial expirou:
        - Requisições AJAX/JSON: retorna JsonResponse de erro 403 com detalhes dos planos.
        - Requisições HTML de navegador: renderiza a tela subscriptions/feature_locked.html com status HTTP 403.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # 1. Identificação da loja no contexto da requisição
            store_slug = kwargs.get('store_slug')
            store = None
            if store_slug:
                store = Store.objects.filter(slug=store_slug).first()
            elif hasattr(request, 'store') and request.store:
                store = request.store
            elif request.user.is_authenticated and hasattr(request.user, 'memberships'):
                membership = request.user.memberships.filter(is_active=True).select_related('store').first()
                if membership:
                    store = membership.store

            # Se não identificar loja (ex: páginas soltas), deixa a view tratar
            if not store:
                return view_func(request, *args, **kwargs)

            # 2. Verificação de permissão no FeatureService
            has_access = FeatureService.can_access_feature(store, feature_code)
            if has_access:
                return view_func(request, *args, **kwargs)

            # 3. Tratamento de Acesso Negado
            is_ajax = (
                request.headers.get('x-requested-with') == 'XMLHttpRequest' or
                'application/json' in request.headers.get('Accept', '') or
                request.path.endswith('/api/')
            )

            feature_obj = Feature.objects.filter(code=feature_code).first()
            plans_with_feature = Plan.objects.filter(
                features__code=feature_code,
                is_active=True
            ).order_by('display_order', 'price')
            subscription = Subscription.objects.filter(store=store).order_by('-created_at').first()
            trial_info = TrialService.check_trial_status(store)

            if is_ajax:
                return JsonResponse({
                    'error': 'feature_locked',
                    'feature_code': feature_code,
                    'feature_name': feature_obj.name if feature_obj else feature_code,
                    'message': 'Esta funcionalidade não está inclusa no seu plano atual ou seu período de testes expirou.',
                    'plans': [
                        {
                            'name': p.name,
                            'slug': p.slug,
                            'price': str(p.price),
                            'billing_cycle': p.get_billing_cycle_display(),
                        } for p in plans_with_feature
                    ]
                }, status=403)

            return render(
                request,
                'subscriptions/feature_locked.html',
                {
                    'store': store,
                    'feature': feature_obj,
                    'feature_code': feature_code,
                    'plans_with_feature': plans_with_feature,
                    'subscription': subscription,
                    'trial_info': trial_info,
                },
                status=403
            )
        return _wrapped_view
    return decorator
