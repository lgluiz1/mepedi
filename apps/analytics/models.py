import urllib.parse
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import StoreBoundedModel


class TrafficVisit(StoreBoundedModel):
    """
    Registro individual de visitação na página pública da loja / cardápio.
    Captura UTMs, referrer e sessão para permitir atribuição e análise de tráfego.
    """
    session_id = models.CharField(
        _('ID da Sessão'),
        max_length=100,
        db_index=True
    )
    utm_source = models.CharField(
        _('Origem (utm_source)'),
        max_length=100,
        blank=True,
        null=True,
        db_index=True
    )
    utm_medium = models.CharField(
        _('Mídia (utm_medium)'),
        max_length=100,
        blank=True,
        null=True,
        db_index=True
    )
    utm_campaign = models.CharField(
        _('Campanha (utm_campaign)'),
        max_length=150,
        blank=True,
        null=True,
        db_index=True
    )
    utm_term = models.CharField(
        _('Termo (utm_term)'),
        max_length=150,
        blank=True,
        null=True
    )
    utm_content = models.CharField(
        _('Conteúdo (utm_content)'),
        max_length=150,
        blank=True,
        null=True
    )
    referrer = models.CharField(
        _('Referenciador (HTTP_REFERER)'),
        max_length=500,
        blank=True,
        null=True
    )
    landing_page = models.CharField(
        _('Página de Entrada'),
        max_length=500,
        blank=True,
        default='/'
    )
    ip_address = models.GenericIPAddressField(
        _('Endereço IP'),
        blank=True,
        null=True
    )
    user_agent = models.TextField(
        _('User Agent'),
        blank=True,
        null=True
    )

    class Meta:
        verbose_name = _('Visita de Tráfego')
        verbose_name_plural = _('Visitas de Tráfego')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['store', 'created_at']),
            models.Index(fields=['store', 'utm_source']),
            models.Index(fields=['store', 'utm_campaign']),
        ]

    def __str__(self):
        source = self.utm_source or 'Direto'
        return f"{self.store.name} - {source} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"

    @property
    def display_source(self) -> str:
        if self.utm_source:
            return self.utm_source.strip().lower()
        if self.referrer:
            ref = self.referrer.lower()
            if 'instagram' in ref:
                return 'instagram'
            if 'whatsapp' in ref or 'wa.me' in ref:
                return 'whatsapp'
            if 'facebook' in ref or 'fb.com' in ref:
                return 'facebook'
            if 'tiktok' in ref:
                return 'tiktok'
            if 'google' in ref:
                return 'google'
            return 'outros / referer'
        return 'direto'


class TrackableLink(StoreBoundedModel):
    """
    Links customizados criados pelo lojista para divulgação externa
    (ex: Instagram bio, campanhas WhatsApp, TikTok, panfletos QR Code).
    Gera automaticamente a URL parametrizada e consolida métricas.
    """
    name = models.CharField(
        _('Nome do Link'),
        max_length=150,
        help_text=_('Identificação interna (ex: Bio do Instagram, Campanha Setembro).')
    )
    slug_code = models.CharField(
        _('Código do Link'),
        max_length=50,
        blank=True,
        db_index=True,
        help_text=_('Identificador amigável único por loja.')
    )
    destination_path = models.CharField(
        _('Caminho de Destino'),
        max_length=255,
        default='/',
        help_text=_('Caminho relativo (ex: / ou /cardapio).')
    )
    utm_source = models.CharField(
        _('Origem (utm_source)'),
        max_length=100,
        help_text=_('Ex: instagram, whatsapp, tiktok, facebook, google, panfleto.')
    )
    utm_medium = models.CharField(
        _('Mídia (utm_medium)'),
        max_length=100,
        blank=True,
        default='social',
        help_text=_('Ex: bio, stories, grupo, qr, cpc.')
    )
    utm_campaign = models.CharField(
        _('Campanha (utm_campaign)'),
        max_length=150,
        blank=True,
        default='',
        help_text=_('Ex: lancamento, setembro, blackfriday.')
    )
    utm_term = models.CharField(
        _('Termo (utm_term)'),
        max_length=150,
        blank=True,
        default=''
    )
    utm_content = models.CharField(
        _('Conteúdo (utm_content)'),
        max_length=150,
        blank=True,
        default=''
    )
    clicks_count = models.PositiveIntegerField(
        _('Cliques Registrados'),
        default=0
    )
    is_active = models.BooleanField(
        _('Ativo'),
        default=True
    )

    class Meta:
        verbose_name = _('Link Rastreável')
        verbose_name_plural = _('Links Rastreáveis')
        ordering = ['-created_at']
        unique_together = ('store', 'slug_code')

    def __str__(self):
        return f"{self.name} ({self.utm_source}) - {self.store.name}"

    def build_url(self, base_url: str = '') -> str:
        """
        Gera a URL pública da loja com todas as tags UTM devidamente encodadas.
        """
        clean_path = f"/{self.store.slug}/"
        if self.destination_path and self.destination_path != '/':
            subpath = self.destination_path.lstrip('/')
            clean_path = f"/{self.store.slug}/{subpath}"

        params = {'utm_source': self.utm_source}
        if self.utm_medium:
            params['utm_medium'] = self.utm_medium
        if self.utm_campaign:
            params['utm_campaign'] = self.utm_campaign
        if self.utm_term:
            params['utm_term'] = self.utm_term
        if self.utm_content:
            params['utm_content'] = self.utm_content

        query_str = urllib.parse.urlencode(params)
        full_path = f"{clean_path}?{query_str}"
        if base_url:
            return f"{base_url.rstrip('/')}{full_path}"
        return full_path


class AnalyticsEvent(StoreBoundedModel):
    """
    Rastreamento de eventos do funil de conversão e comportamento do consumidor.
    """
    EVENT_PAGE_VIEW = 'PAGE_VIEW'
    EVENT_PRODUCT_VIEW = 'PRODUCT_VIEW'
    EVENT_ADD_TO_CART = 'ADD_TO_CART'
    EVENT_CHECKOUT_STARTED = 'CHECKOUT_STARTED'
    EVENT_ORDER_CREATED = 'ORDER_CREATED'
    EVENT_ORDER_COMPLETED = 'ORDER_COMPLETED'
    EVENT_ORDER_CANCELLED = 'ORDER_CANCELLED'

    EVENT_CHOICES = [
        (EVENT_PAGE_VIEW, _('Visualização de Página')),
        (EVENT_PRODUCT_VIEW, _('Visualização de Produto')),
        (EVENT_ADD_TO_CART, _('Adicionado ao Carrinho')),
        (EVENT_CHECKOUT_STARTED, _('Início de Checkout')),
        (EVENT_ORDER_CREATED, _('Pedido Criado')),
        (EVENT_ORDER_COMPLETED, _('Pedido Concluído')),
        (EVENT_ORDER_CANCELLED, _('Pedido Cancelado')),
    ]

    session_id = models.CharField(
        _('ID da Sessão'),
        max_length=100,
        db_index=True
    )
    event_type = models.CharField(
        _('Tipo de Evento'),
        max_length=35,
        choices=EVENT_CHOICES,
        db_index=True
    )
    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='analytics_events',
        verbose_name=_('Produto Relacionado')
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='analytics_events',
        verbose_name=_('Pedido Relacionado')
    )
    metadata = models.JSONField(
        _('Metadados'),
        default=dict,
        blank=True
    )

    class Meta:
        verbose_name = _('Evento de Analytics')
        verbose_name_plural = _('Eventos de Analytics')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['store', 'event_type', 'created_at']),
            models.Index(fields=['store', 'session_id']),
        ]

    def __str__(self):
        return f"{self.store.name} - {self.event_type} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"
