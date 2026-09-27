from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from orders.models import Order
from ..models import Subscription


class TrialService:
    """
    Serviço centralizado para gerenciamento e auditoria do período de Trial gratuito.

    REGRAS DO TRIAL:
    - Máximo de 30 dias;
    - Máximo de 300 pedidos válidos;
    - Máximo de R$ 2.000,00 em faturamento de vendas válidas;
    - Encerra quando QUALQUER UMA das 3 condições for atingida primeiro;
    - Pedidos cancelados (Order.STATUS_CANCELLED) NÃO entram na contagem de pedidos nem no faturamento;
    - Dados nunca são apagados quando o Trial termina.

    REGRA PARA PLANOS PAGOS:
    - NUNCA aplicar limites de pedidos ou faturamento a assinaturas pagas (ACTIVE).
    """
    TRIAL_MAX_DAYS = 30
    TRIAL_MAX_ORDERS = 300
    TRIAL_MAX_REVENUE = Decimal("2000.00")

    @classmethod
    def get_valid_trial_orders_queryset(cls, store, trial_started_at=None):
        """
        Retorna o QuerySet de pedidos reais válidos para o cálculo do trial.
        Exclui explicitamente os pedidos cancelados.
        """
        qs = Order.objects.filter(store=store)
        if trial_started_at:
            qs = qs.filter(created_at__gte=trial_started_at)
        # Pedidos cancelados não contam
        return qs.exclude(status=Order.STATUS_CANCELLED)

    @classmethod
    def calculate_metrics(cls, store, trial_started_at=None):
        """
        Calcula os totais reais de pedidos e receita a partir do banco de pedidos.
        """
        qs = cls.get_valid_trial_orders_queryset(store, trial_started_at)
        orders_count = qs.count()
        revenue_agg = qs.aggregate(total_sum=Sum('total'))
        revenue_total = revenue_agg['total_sum'] or Decimal('0.00')

        now = timezone.now()
        if trial_started_at:
            delta = now - trial_started_at
            days_used = max(0, delta.days)
        else:
            days_used = 0

        days_remaining = max(0, cls.TRIAL_MAX_DAYS - days_used)

        return {
            'orders_count': orders_count,
            'revenue_total': revenue_total,
            'days_used': days_used,
            'days_remaining': days_remaining,
        }

    @classmethod
    def check_trial_status(cls, store):
        """
        Verifica a situação do Trial para uma loja.
        Retorna dicionário completo com métricas e status.
        Atualiza o status da Subscription no banco caso o Trial tenha acabado de expirar.
        """
        # Busca a assinatura atual da loja
        subscription = Subscription.objects.filter(
            store=store,
            status__in=[
                Subscription.STATUS_TRIAL,
                Subscription.STATUS_ACTIVE,
                Subscription.STATUS_PAST_DUE,
                Subscription.STATUS_SUSPENDED,
                Subscription.STATUS_CANCELLED,
                Subscription.STATUS_EXPIRED,
            ]
        ).order_by('-created_at').first()

        # Se não possui assinatura registrada
        if not subscription:
            return {
                'is_active': False,
                'is_expired': True,
                'expired_reason': 'NO_SUBSCRIPTION',
                'days_used': 0,
                'days_remaining': 0,
                'orders_count': 0,
                'orders_limit': cls.TRIAL_MAX_ORDERS,
                'revenue_total': Decimal('0.00'),
                'revenue_limit': cls.TRIAL_MAX_REVENUE,
                'subscription': None,
            }

        # REGRA ABSOLUTA: Se a assinatura for ACTIVE (plano pago), limites NÃO SE APLICAM
        if subscription.status == Subscription.STATUS_ACTIVE:
            return {
                'is_active': True,
                'is_expired': False,
                'expired_reason': None,
                'days_used': 0,
                'days_remaining': 9999,
                'orders_count': cls.get_valid_trial_orders_queryset(store).count(),
                'orders_limit': None,  # ILIMITADO
                'revenue_total': cls.get_valid_trial_orders_queryset(store).aggregate(total=Sum('total'))['total'] or Decimal('0.00'),
                'revenue_limit': None,  # ILIMITADO
                'subscription': subscription,
            }

        # Se já estiver expirada ou cancelada
        if subscription.status in [Subscription.STATUS_EXPIRED, Subscription.STATUS_CANCELLED, Subscription.STATUS_SUSPENDED]:
            metrics = cls.calculate_metrics(store, subscription.trial_started_at)
            return {
                'is_active': False,
                'is_expired': True,
                'expired_reason': subscription.trial_expired_reason or 'CANCELLED',
                'days_used': metrics['days_used'],
                'days_remaining': 0,
                'orders_count': metrics['orders_count'],
                'orders_limit': cls.TRIAL_MAX_ORDERS,
                'revenue_total': metrics['revenue_total'],
                'revenue_limit': cls.TRIAL_MAX_REVENUE,
                'subscription': subscription,
            }

        # Status é TRIAL: calcula métricas reais
        metrics = cls.calculate_metrics(store, subscription.trial_started_at)
        orders_count = metrics['orders_count']
        revenue_total = metrics['revenue_total']
        days_used = metrics['days_used']
        days_remaining = metrics['days_remaining']

        now = timezone.now()
        is_expired = False
        expired_reason = None

        # Valida a primeira condição que encerra o Trial:
        # 1. 300 pedidos válidos
        # 2. R$ 2.000,00 em vendas válidas
        # 3. 30 dias corridos
        if orders_count >= cls.TRIAL_MAX_ORDERS:
            is_expired = True
            expired_reason = Subscription.REASON_ORDERS_LIMIT
        elif revenue_total >= cls.TRIAL_MAX_REVENUE:
            is_expired = True
            expired_reason = Subscription.REASON_REVENUE_LIMIT
        elif days_used >= cls.TRIAL_MAX_DAYS or (subscription.trial_ends_at and now >= subscription.trial_ends_at):
            is_expired = True
            expired_reason = Subscription.REASON_DAYS_LIMIT

        # Se expirou, atualiza a assinatura de forma persistente
        if is_expired:
            subscription.status = Subscription.STATUS_EXPIRED
            subscription.trial_expired_reason = expired_reason
            subscription.save(update_fields=['status', 'trial_expired_reason', 'updated_at'])

        return {
            'is_active': not is_expired,
            'is_expired': is_expired,
            'expired_reason': expired_reason,
            'days_used': days_used,
            'days_remaining': days_remaining if not is_expired else 0,
            'orders_count': orders_count,
            'orders_limit': cls.TRIAL_MAX_ORDERS,
            'revenue_total': revenue_total,
            'revenue_limit': cls.TRIAL_MAX_REVENUE,
            'subscription': subscription,
        }
