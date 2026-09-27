import json
import logging
import urllib.request
import urllib.error
from decimal import Decimal
from typing import Dict, Any, Optional
from django.conf import settings
from .base import PaymentGateway

logger = logging.getLogger(__name__)


class MercadoPagoGateway(PaymentGateway):
    """
    Integração com Mercado Pago para assinaturas e pagamentos do SaaS MePedi.
    Não armazena tokens no código. Utiliza PaymentGatewayConfig ou variáveis de ambiente.
    Utiliza urllib.request da biblioteca padrão do Python para chamadas REST seguras e sem dependências extras.
    """
    API_BASE_URL = "https://api.mercadopago.com"

    def __init__(self, config=None):
        super().__init__(config=config)
        self.access_token = ""
        self.public_key = ""
        self.environment = "SANDBOX"

        if self.config:
            self.access_token = self.config.access_token
            self.public_key = self.config.public_key
            self.environment = self.config.environment
        else:
            # Fallback seguro para settings/env sem hardcoding
            self.access_token = getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', '')
            self.public_key = getattr(settings, 'MERCADOPAGO_PUBLIC_KEY', '')
            self.environment = getattr(settings, 'MERCADOPAGO_ENVIRONMENT', 'SANDBOX')

    def test_connection(self) -> bool:
        """
        Valida a existência e a resposta das credenciais configuradas.
        """
        if not self.access_token:
            logger.warning("Mercado Pago: Access Token não configurado.")
            return False
        try:
            req = urllib.request.Request(
                f"{self.API_BASE_URL}/users/me",
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"Mercado Pago: Falha no teste de conexão: {e}")
            return False

    def _api_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Executa requisição HTTP autenticada contra a API do Mercado Pago.
        """
        if not self.access_token:
            return None

        url = f"{self.API_BASE_URL}{endpoint}"
        body_bytes = None
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        if data is not None:
            body_bytes = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                resp_data = response.read().decode("utf-8")
                return json.loads(resp_data) if resp_data else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error(f"Mercado Pago API Error [{e.code}] on {url}: {err_body}")
            return None
        except Exception as e:
            logger.error(f"Mercado Pago Connection Error on {url}: {str(e)}")
            return None

    def create_customer(self, store, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estrutura de criação ou identificação de cliente no Mercado Pago.
        """
        email = user_data.get('email', '')
        if not email and hasattr(store, 'owner') and store.owner:
            email = store.owner.email

        customer_payload = {
            'email': email or f"store_{store.id}@mepedi.com.br",
            'first_name': user_data.get('first_name', store.name[:30]),
            'description': f"Lojista MePedi - {store.name}",
        }

        if self.access_token:
            api_resp = self._api_request('POST', '/v1/customers', customer_payload)
            if api_resp and 'id' in api_resp:
                return api_resp

        return {
            'id': f"mp_cust_{store.id}",
            'email': customer_payload['email'],
            'first_name': customer_payload['first_name'],
        }

    def create_checkout_preference(
        self,
        subscription,
        plan,
        return_urls: Optional[Dict[str, str]] = None,
        payer_data: Optional[Dict[str, Any]] = None,
        external_reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Gera uma preferência de checkout no Mercado Pago (Checkout Pro / Transparente).
        Configura itens, preços, URLs de retorno e webhook de notificação.
        """
        store = subscription.store
        ref = external_reference or f"mepedi_sub_{subscription.id}_{plan.id}"

        # Montagem do payer seguro
        payer = {}
        if payer_data:
            if payer_data.get('email'):
                payer['email'] = payer_data['email']
            if payer_data.get('name'):
                payer['name'] = payer_data['name']
        elif hasattr(store, 'owner') and store.owner and store.owner.email:
            payer['email'] = store.owner.email
            payer['name'] = store.owner.get_full_name() or store.name

        preference_payload = {
            'items': [
                {
                    'id': str(plan.id),
                    'title': f"MePedi - Plano {plan.name}",
                    'description': plan.description[:250] if plan.description else f"Assinatura do Plano {plan.name} - MePedi",
                    'quantity': 1,
                    'unit_price': float(plan.price),
                    'currency_id': 'BRL',
                }
            ],
            'payer': payer,
            'external_reference': ref,
            'statement_descriptor': 'MEPEDI SAAS',
            'auto_return': 'approved',
        }

        if return_urls:
            back_urls = {}
            if return_urls.get('success'):
                back_urls['success'] = return_urls['success']
            if return_urls.get('pending'):
                back_urls['pending'] = return_urls['pending']
            if return_urls.get('failure'):
                back_urls['failure'] = return_urls['failure']
            if back_urls:
                preference_payload['back_urls'] = back_urls

            if return_urls.get('notification_url'):
                preference_payload['notification_url'] = return_urls['notification_url']

        # Se houver token configurado, faz chamada real à API
        if self.access_token:
            api_resp = self._api_request('POST', '/checkout/preferences', preference_payload)
            if api_resp and 'id' in api_resp:
                return {
                    'id': api_resp['id'],
                    'init_point': api_resp.get('init_point'),
                    'sandbox_init_point': api_resp.get('sandbox_init_point') or api_resp.get('init_point'),
                    'preference_data': preference_payload,
                    'raw': api_resp
                }

        # Fallback para ambiente de desenvolvimento/testes locais sem token live
        pref_id = f"pref_{subscription.id}_{plan.slug}"
        return {
            'id': pref_id,
            'init_point': f"https://www.mercadopago.com.br/checkout/v1/redirect?pref_id={pref_id}",
            'sandbox_init_point': f"https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id={pref_id}",
            'preference_data': preference_payload,
            'raw': {}
        }

    def get_payment_info(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """
        Consulta informações oficiais e verificadas de um pagamento diretamente na API do Mercado Pago.
        """
        if not self.access_token or not payment_id:
            return None
        return self._api_request('GET', f'/v1/payments/{payment_id}')

    def handle_webhook(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Normaliza os eventos de webhook do Mercado Pago (IPN e Webhooks V1/V2).
        Suporta notificações no formato:
        - {"type": "payment", "data": {"id": "12345"}}
        - {"action": "payment.created", "data": {"id": "12345"}}
        - {"topic": "payment", "resource": "https://api.mercadopago.com/v1/payments/12345"}
        """
        event_type = payload.get('type') or payload.get('action') or payload.get('topic') or 'unknown'
        data_obj = payload.get('data') or {}
        resource_id = str(data_obj.get('id') or payload.get('id') or '')

        # Se for recurso em formato de URL
        if not resource_id and 'resource' in payload:
            resource_parts = str(payload['resource']).rstrip('/').split('/')
            resource_id = resource_parts[-1]

        # Se tiver credencial ativa e o recurso for um payment id numérico, busca status oficial verificado na API
        verified_payment = None
        if self.access_token and resource_id and resource_id.isdigit():
            verified_payment = self.get_payment_info(resource_id)

        status_map = {
            'payment.created': 'PENDING',
            'payment.updated': 'APPROVED',
            'payment': 'APPROVED',
            'authorized': 'APPROVED',
            'approved': 'APPROVED',
            'in_process': 'PENDING',
            'pending': 'PENDING',
            'rejected': 'REJECTED',
            'cancelled': 'CANCELLED',
            'refunded': 'REFUNDED',
            'charged_back': 'REFUNDED',
        }

        if verified_payment:
            mp_status = verified_payment.get('status', 'pending').lower()
            normalized_status = status_map.get(mp_status, 'PENDING')
            amount = Decimal(str(verified_payment.get('transaction_amount', '0.00')))
            external_reference = verified_payment.get('external_reference') or ''
            raw_data = verified_payment
        else:
            normalized_status = status_map.get(event_type, 'PENDING')
            if 'status' in payload:
                normalized_status = status_map.get(payload['status'], payload['status'].upper())

            amount = Decimal('0.00')
            if 'transaction_amount' in payload:
                amount = Decimal(str(payload['transaction_amount']))
            elif 'data' in payload and 'transaction_amount' in payload['data']:
                amount = Decimal(str(payload['data']['transaction_amount']))

            external_reference = payload.get('external_reference') or ''
            raw_data = payload

        return {
            'event_type': event_type,
            'external_id': resource_id or str(payload.get('id', '')),
            'status': normalized_status,
            'amount': amount,
            'external_reference': external_reference,
            'subscription_id': payload.get('subscription_id') or '',
            'raw': raw_data,
        }
