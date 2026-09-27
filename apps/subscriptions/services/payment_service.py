import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from ..models import Subscription, Plan, PaymentGatewayConfig, PaymentHistory, WebhookEvent
from ..gateways.mercadopago import MercadoPagoGateway
from .subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Serviço orquestrador de pagamentos, checkout e webhooks do SaaS MePedi.
    Desacopla regras de negócio dos provedores externos de pagamento (Mercado Pago, etc).
    Garante idempotência estrita via WebhookEvent e transações atômicas com locks.
    """

    def __init__(self, gateway_name: str = 'MERCADOPAGO'):
        self.gateway_name = gateway_name.upper()

    def get_gateway_instance(self):
        """
        Instancia o gateway configurado para o ambiente correspondente.
        """
        config = PaymentGatewayConfig.objects.filter(
            gateway=self.gateway_name,
            is_active=True
        ).first()

        if self.gateway_name == 'MERCADOPAGO':
            return MercadoPagoGateway(config=config)
        raise NotImplementedError(f"Gateway {self.gateway_name} ainda não suportado.")

    def create_subscription_checkout(self, store, plan, user=None, request=None) -> dict:
        """
        Gera uma sessão/preferência de checkout segura para a contratação ou upgrade de plano.
        Registra a intenção em PaymentHistory (status PENDING) e retorna a URL de checkout do gateway.
        """
        gateway = self.get_gateway_instance()

        # 1. Recupera ou garante a assinatura existente da loja
        subscription = SubscriptionService.get_current_subscription(store)
        if not subscription:
            subscription = SubscriptionService.start_trial(store)

        # 2. Cria o registro de intenção de pagamento no histórico
        with transaction.atomic():
            payment_history = PaymentHistory.objects.create(
                subscription=subscription,
                gateway=self.gateway_name,
                amount=plan.price,
                status=PaymentHistory.STATUS_PENDING,
                raw_payload={
                    'plan_id': plan.id,
                    'plan_slug': plan.slug,
                    'plan_name': plan.name,
                    'store_id': store.id,
                    'store_slug': store.slug,
                }
            )

        # 3. Monta URLs de retorno do checkout
        if request:
            base_url = request.build_absolute_uri('/')[:-1]
        else:
            base_url = 'http://127.0.0.1:8000'

        return_urls = {
            'success': f"{base_url}/painel/{store.slug}/assinatura/retorno/?status=success&plan={plan.slug}&payment_id={payment_history.id}",
            'pending': f"{base_url}/painel/{store.slug}/assinatura/retorno/?status=pending&plan={plan.slug}&payment_id={payment_history.id}",
            'failure': f"{base_url}/painel/{store.slug}/assinatura/retorno/?status=failure&plan={plan.slug}&payment_id={payment_history.id}",
            'notification_url': f"{base_url}/api/v1/subscriptions/webhook/{self.gateway_name.lower()}/",
        }

        # 4. Dados do pagador
        payer_data = {}
        if user and getattr(user, 'is_authenticated', False):
            payer_data['email'] = user.email
            payer_data['name'] = user.get_full_name() or store.name
        elif hasattr(store, 'owner') and store.owner:
            payer_data['email'] = store.owner.email
            payer_data['name'] = store.owner.get_full_name() or store.name

        external_reference = f"mepedi_sub_{subscription.id}_{plan.id}_{payment_history.id}"

        # 5. Gera preferência no Gateway
        preference = gateway.create_checkout_preference(
            subscription=subscription,
            plan=plan,
            return_urls=return_urls,
            payer_data=payer_data,
            external_reference=external_reference
        )

        pref_id = preference.get('id', '')
        # Atualiza o registro de pagamento com o ID da preferência do gateway
        payment_history.external_id = pref_id
        payment_history.raw_payload = preference
        payment_history.save(update_fields=['external_id', 'raw_payload', 'updated_at'])

        # Determina a URL de redirecionamento (sandbox ou live)
        is_sandbox = getattr(gateway, 'environment', 'SANDBOX') == 'SANDBOX'
        checkout_url = preference.get('sandbox_init_point') if is_sandbox else preference.get('init_point')
        if not checkout_url:
            checkout_url = preference.get('init_point') or preference.get('sandbox_init_point')

        return {
            'checkout_url': checkout_url,
            'preference_id': pref_id,
            'payment_history_id': payment_history.id,
            'plan': plan,
        }

    def process_webhook_event(self, gateway: str, external_id: str, event_type: str, payload: dict) -> dict:
        """
        Processa eventos recebidos de webhook de forma 100% idempotente.
        Se o evento com (gateway, external_id) já foi processado com sucesso:
        - Detecta duplicidade;
        - Não cria histórico repetido;
        - Não altera assinatura repetidamente;
        - Retorna status ALREADY_PROCESSED.
        """
        gateway = gateway.upper()

        # 1. Registro atômico do WebhookEvent para garantia absoluta de concorrência e idempotência
        with transaction.atomic():
            event, created = WebhookEvent.objects.select_for_update().get_or_create(
                gateway=gateway,
                external_id=external_id,
                defaults={
                    'event_type': event_type,
                    'payload': payload,
                    'status': WebhookEvent.STATUS_PENDING,
                }
            )

            # Se o evento já foi processado anteriormente, garante idempotência absoluta
            if not created and event.status == WebhookEvent.STATUS_PROCESSED:
                logger.info(f"Webhook idempotente: evento {gateway}:{external_id} já processado anteriormente.")
                return {
                    'status': 'ALREADY_PROCESSED',
                    'event_id': event.id,
                    'external_id': external_id,
                    'message': 'Evento já processado anteriormente com sucesso.'
                }

            # Atualiza o payload e o tipo se necessário
            if not created and event.status in [WebhookEvent.STATUS_PENDING, WebhookEvent.STATUS_FAILED]:
                event.payload = payload
                event.event_type = event_type
                event.status = WebhookEvent.STATUS_PENDING
                event.error_message = ''
                event.save(update_fields=['payload', 'event_type', 'status', 'error_message', 'updated_at'])

        # 2. Processa o evento através do Gateway correspondente
        try:
            gateway_inst = self.get_gateway_instance()
            normalized = gateway_inst.handle_webhook(payload)

            normalized_status = normalized.get('status', 'PENDING')
            amount = normalized.get('amount') or Decimal('0.00')
            external_reference = normalized.get('external_reference') or payload.get('external_reference', '')

            # Extração de referências vinculadas: mepedi_sub_{sub_id}_{plan_id}_{payment_history_id}
            sub_id = None
            plan_id = None
            payment_hist_id = None

            if external_reference and external_reference.startswith('mepedi_sub_'):
                parts = external_reference.split('_')
                if len(parts) >= 5:
                    sub_id = parts[2]
                    plan_id = parts[3]
                    payment_hist_id = parts[4]
            elif external_reference and external_reference.isdigit():
                sub_id = external_reference

            with transaction.atomic():
                # Localiza a assinatura associada
                subscription = None
                if sub_id:
                    subscription = Subscription.objects.select_for_update().filter(id=sub_id).first()

                if not subscription:
                    # Tenta pela subscription_id normalizada
                    sub_norm_id = normalized.get('subscription_id')
                    if sub_norm_id:
                        subscription = Subscription.objects.select_for_update().filter(id=sub_norm_id).first()

                # Localiza ou atualiza o PaymentHistory
                payment_history = None
                if payment_hist_id:
                    payment_history = PaymentHistory.objects.select_for_update().filter(id=payment_hist_id).first()
                if not payment_history and external_id:
                    payment_history = PaymentHistory.objects.select_for_update().filter(external_id=external_id).first()

                # Localiza o plano pretendido
                plan = None
                if plan_id:
                    plan = Plan.objects.filter(id=plan_id).first()
                elif payment_history and isinstance(payment_history.raw_payload, dict) and payment_history.raw_payload.get('plan_id'):
                    plan = Plan.objects.filter(id=payment_history.raw_payload['plan_id']).first()
                elif subscription and subscription.plan:
                    plan = subscription.plan

                # Atualiza ou cria o registro financeiro
                if payment_history:
                    payment_history.status = normalized_status
                    if amount > Decimal('0.00'):
                        payment_history.amount = amount
                    if normalized_status == 'APPROVED':
                        payment_history.payment_date = timezone.now()
                    payment_history.save(update_fields=['status', 'amount', 'payment_date', 'updated_at'])
                elif subscription:
                    PaymentHistory.objects.create(
                        subscription=subscription,
                        gateway=gateway,
                        external_id=external_id,
                        amount=amount if amount > Decimal('0.00') else (plan.price if plan else Decimal('0.00')),
                        status=normalized_status,
                        payment_date=timezone.now() if normalized_status == 'APPROVED' else None,
                        raw_payload=payload
                    )

                # Se o pagamento foi aprovado, ativa ou renova a assinatura da loja
                if normalized_status == 'APPROVED' and subscription:
                    target_plan = plan or subscription.plan
                    if target_plan:
                        SubscriptionService.activate_plan(store=subscription.store, plan=target_plan)
                    else:
                        subscription.status = Subscription.STATUS_ACTIVE
                        subscription.current_period_start = timezone.now()
                        subscription.current_period_end = timezone.now() + timezone.timedelta(days=30)
                        subscription.save(update_fields=['status', 'current_period_start', 'current_period_end', 'updated_at'])

                # Marca evento como processado com sucesso
                event.status = WebhookEvent.STATUS_PROCESSED
                event.processed_at = timezone.now()
                event.save(update_fields=['status', 'processed_at', 'updated_at'])

                return {
                    'status': 'PROCESSED',
                    'event_id': event.id,
                    'external_id': external_id,
                    'payment_status': normalized_status,
                    'store_id': subscription.store.id if subscription else None
                }

        except Exception as e:
            logger.error(f"Erro ao processar webhook {gateway}:{external_id}: {str(e)}", exc_info=True)
            with transaction.atomic():
                event.status = WebhookEvent.STATUS_FAILED
                event.error_message = str(e)
                event.save(update_fields=['status', 'error_message', 'updated_at'])
            return {
                'status': 'FAILED',
                'event_id': event.id,
                'external_id': external_id,
                'error': str(e)
            }
