import uuid
import logging
from typing import Optional, Tuple
from django.http import HttpRequest
from django.utils.text import slugify
from django.db import models
from stores.models import Store
from .models import TrafficVisit, TrackableLink, AnalyticsEvent

logger = logging.getLogger(__name__)


class AnalyticsService:
    """
    Camada de serviço para captura e registro de tráfego, eventos e links rastreáveis.
    Projetada para ser à prova de falhas (fail-safe): nunca deve interromper
    o fluxo normal de compra ou visualização do cliente caso ocorra erro de telemetria.
    """

    @classmethod
    def get_session_id(cls, request: HttpRequest) -> str:
        """
        Obtém ou inicializa com segurança o identificador de sessão de telemetria.
        """
        session_key = 'analytics_session_id'
        session_id = request.session.get(session_key)
        if not session_id:
            session_id = uuid.uuid4().hex
            request.session[session_key] = session_id
        return session_id

    @classmethod
    def get_client_ip(cls, request: HttpRequest) -> Optional[str]:
        """
        Extrai o IP do visitante considerando proxies reversos e headers comuns.
        """
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            ip = x_forwarded.split(',')[0].strip()
            return ip[:45]
        return request.META.get('REMOTE_ADDR')

    @classmethod
    def record_visit(cls, request: HttpRequest, store: Store) -> Optional[TrafficVisit]:
        """
        Registra a visita pública de um cliente ao cardápio da loja.
        Captura parâmetros UTM, Referrer, IP e vincula à sessão.
        """
        try:
            session_id = cls.get_session_id(request)

            utm_source = request.GET.get('utm_source', '').strip()[:100] or None
            utm_medium = request.GET.get('utm_medium', '').strip()[:100] or None
            utm_campaign = request.GET.get('utm_campaign', '').strip()[:150] or None
            utm_term = request.GET.get('utm_term', '').strip()[:150] or None
            utm_content = request.GET.get('utm_content', '').strip()[:150] or None

            referrer = request.META.get('HTTP_REFERER', '')[:500] or None
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            ip_address = cls.get_client_ip(request)
            landing_page = request.path[:500]

            # Salva parâmetros na sessão para atribuição futura de pedidos
            if utm_source or utm_campaign:
                request.session['analytics_attribution'] = {
                    'utm_source': utm_source,
                    'utm_medium': utm_medium,
                    'utm_campaign': utm_campaign,
                    'utm_term': utm_term,
                    'utm_content': utm_content,
                }

            visit = TrafficVisit.objects.create(
                store=store,
                session_id=session_id,
                utm_source=utm_source,
                utm_medium=utm_medium,
                utm_campaign=utm_campaign,
                utm_term=utm_term,
                utm_content=utm_content,
                referrer=referrer,
                landing_page=landing_page,
                ip_address=ip_address,
                user_agent=user_agent
            )

            # Se houver link rastreável cadastrado correspondente, incrementa o contador de cliques
            if utm_source and utm_campaign:
                TrackableLink.objects.filter(
                    store=store,
                    utm_source__iexact=utm_source,
                    utm_campaign__iexact=utm_campaign,
                    is_active=True
                ).update(clicks_count=models.F('clicks_count') + 1)

            # Registra evento de PAGE_VIEW no funil
            cls.record_event(
                store=store,
                session_id=session_id,
                event_type=AnalyticsEvent.EVENT_PAGE_VIEW,
                metadata={'landing_page': landing_page, 'utm_source': utm_source}
            )

            return visit
        except Exception as e:
            logger.warning(f"Erro silencioso ao registrar TrafficVisit: {e}")
            return None

    @classmethod
    def record_event(
        cls,
        store: Store,
        session_id: str,
        event_type: str,
        product=None,
        order=None,
        metadata: dict = None
    ) -> Optional[AnalyticsEvent]:
        """
        Registra um evento comportamental ou etapa do funil (PAGE_VIEW, ADD_TO_CART, etc).
        """
        try:
            return AnalyticsEvent.objects.create(
                store=store,
                session_id=session_id,
                event_type=event_type,
                product=product,
                order=order,
                metadata=metadata or {}
            )
        except Exception as e:
            logger.warning(f"Erro silencioso ao registrar AnalyticsEvent ({event_type}): {e}")
            return None

    @classmethod
    def create_trackable_link(
        cls,
        store: Store,
        name: str,
        utm_source: str,
        utm_campaign: str = '',
        utm_medium: str = 'social',
        destination_path: str = '/',
        utm_term: str = '',
        utm_content: str = ''
    ) -> TrackableLink:
        """
        Cria com segurança um link rastreável com slug_code único por loja.
        """
        base_slug = slugify(name)[:35] or 'link'
        slug_candidate = base_slug
        counter = 1
        while TrackableLink.objects.filter(store=store, slug_code=slug_candidate).exists():
            slug_candidate = f"{base_slug}-{counter}"
            counter += 1

        return TrackableLink.objects.create(
            store=store,
            name=name.strip(),
            slug_code=slug_candidate,
            destination_path=destination_path.strip() or '/',
            utm_source=utm_source.strip().lower(),
            utm_medium=utm_medium.strip().lower() or 'social',
            utm_campaign=utm_campaign.strip().lower(),
            utm_term=utm_term.strip(),
            utm_content=utm_content.strip()
        )
