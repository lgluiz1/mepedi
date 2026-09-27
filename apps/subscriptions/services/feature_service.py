from .trial_service import TrialService
from ..models import Subscription, Feature


class FeatureService:
    """
    Ponto central para autorização de funcionalidades (Features) no SaaS MePedi.

    FLUXO DE DECISÃO:
    1. Sem assinatura cadastrada -> False
    2. TRIAL Ativo (dentro dos limites de 30 dias / 300 pedidos / R$ 2.000) -> True para TODAS as features
    3. TRIAL Expirado -> False
    4. Assinatura ACTIVE (Plano Pago):
       - Se a feature estiver vinculada ao plano contratado e ativa -> True
       - Se não estiver vinculada -> False
    5. PAST_DUE / SUSPENDED / CANCELLED / EXPIRED -> False
    """

    @classmethod
    def can_access_feature(cls, store, feature_code: str) -> bool:
        """
        Determina se a loja possui permissão para acessar a funcionalidade solicitada.
        """
        if not store:
            return False

        # Busca a assinatura mais recente da loja
        subscription = Subscription.objects.filter(
            store=store
        ).order_by('-created_at').first()

        if not subscription:
            return False

        # Se for TRIAL, avalia se continua ativo ou se estourou os limites
        if subscription.status == Subscription.STATUS_TRIAL:
            trial_info = TrialService.check_trial_status(store)
            if trial_info['is_active']:
                # Durante o Trial ativo, TODAS as features ficam liberadas
                return True
            return False

        # Se a assinatura for ACTIVE (plano pago comercial)
        if subscription.status == Subscription.STATUS_ACTIVE:
            if not subscription.plan or not subscription.plan.is_active:
                return False

            # Verifica se o código da feature está no plano contratado
            return subscription.plan.features.filter(
                code=feature_code,
                is_active=True
            ).exists()

        # Demais status (PAST_DUE, SUSPENDED, CANCELLED, EXPIRED): Acesso negado
        return False

    @classmethod
    def get_accessible_features(cls, store) -> list:
        """
        Retorna a lista de códigos de todas as features liberadas para a loja.
        """
        if not store:
            return []

        subscription = Subscription.objects.filter(
            store=store
        ).order_by('-created_at').first()

        if not subscription:
            return []

        if subscription.status == Subscription.STATUS_TRIAL:
            trial_info = TrialService.check_trial_status(store)
            if trial_info['is_active']:
                return list(Feature.objects.filter(is_active=True).values_list('code', flat=True))
            return []

        if subscription.status == Subscription.STATUS_ACTIVE:
            if not subscription.plan or not subscription.plan.is_active:
                return []
            return list(subscription.plan.features.filter(is_active=True).values_list('code', flat=True))

        return []


def can_access_feature(store, feature_code: str) -> bool:
    """
    Função utilitária direta para checagem rápida em views, context processors e decorators.
    """
    return FeatureService.can_access_feature(store, feature_code)


def get_accessible_features(store) -> list:
    """
    Retorna a lista de códigos de funcionalidades ativas para o estabelecimento.
    """
    return FeatureService.get_accessible_features(store)

