from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from core.models import TimeStampedModel, StoreBoundedModel
from .utils import generate_unique_slug


class Store(TimeStampedModel):
    """
    Entidade central do SaaS Multi-Loja.
    Representa o estabelecimento comercial e seu isolamento lógico.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_stores',
        verbose_name=_('Proprietário')
    )
    name = models.CharField(
        _('Nome do Estabelecimento'),
        max_length=150,
        help_text=_('Ex: Lanchonete do Luiz')
    )
    slug = models.SlugField(
        _('Slug / URL Amigável'),
        max_length=160,
        unique=True,
        db_index=True,
        help_text=_('Identificador da URL pública da loja (ex: lanchonete-do-luiz)')
    )
    document = models.CharField(
        _('CPF ou CNPJ'),
        max_length=20,
        blank=True,
        help_text=_('Documento fiscal do lojista ou empresa.')
    )
    phone = models.CharField(
        _('Telefone Fixo / Comercial'),
        max_length=20,
        blank=True
    )
    whatsapp = models.CharField(
        _('WhatsApp para Pedidos'),
        max_length=20,
        help_text=_('Número que receberá as notificações e mensagens de pedidos.')
    )
    description = models.TextField(
        _('Descrição da Loja'),
        blank=True,
        help_text=_('Apresentação exibida no topo do cardápio digital.')
    )

    # Identidade Visual
    logo = models.ImageField(
        _('Logotipo'),
        upload_to='stores/logos/',
        blank=True,
        null=True
    )
    banner = models.ImageField(
        _('Banner de Cabeçalho'),
        upload_to='stores/banners/',
        blank=True,
        null=True
    )

    # Endereço Comercial
    street = models.CharField(_('Rua / Logradouro'), max_length=150, blank=True)
    number = models.CharField(_('Número'), max_length=20, blank=True)
    complement = models.CharField(_('Complemento'), max_length=100, blank=True)
    neighborhood = models.CharField(_('Bairro'), max_length=100, blank=True)
    city = models.CharField(_('Cidade'), max_length=100, blank=True)
    state = models.CharField(_('Estado (UF)'), max_length=2, blank=True)
    postal_code = models.CharField(_('CEP'), max_length=10, blank=True)

    # Operação e Status
    is_active = models.BooleanField(
        _('Loja Ativa na Plataforma'),
        default=True,
        help_text=_('Define se a loja pode operar no SaaS.')
    )
    is_open = models.BooleanField(
        _('Aberta para Pedidos'),
        default=False,
        help_text=_('Controle manual de abertura da loja.')
    )
    is_paused = models.BooleanField(
        _('Pedidos Pausados'),
        default=False,
        help_text=_('Pausa temporária de novos pedidos (ex: cozinha lotada).')
    )

    # Configurações Comerciais
    minimum_order_value = models.DecimalField(
        _('Valor Mínimo do Pedido'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    estimated_delivery_time_min = models.PositiveIntegerField(
        _('Tempo Estimado Mínimo (min)'),
        default=30
    )
    estimated_delivery_time_max = models.PositiveIntegerField(
        _('Tempo Estimado Máximo (min)'),
        default=60
    )

    # Modalidades de Atendimento
    allows_delivery = models.BooleanField(
        _('Aceita Entrega / Delivery'),
        default=True
    )
    allows_pickup = models.BooleanField(
        _('Aceita Retirada no Local'),
        default=True
    )
    fixed_delivery_fee = models.DecimalField(
        _('Taxa Fixa de Entrega (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Valor fixo cobrado por entrega. Deixe 0.00 para entrega grátis.')
    )

    # Operação de Cozinha e Cupom
    preparation_time_minutes = models.PositiveIntegerField(
        _('Tempo Padrão de Preparo (min)'),
        default=30,
        help_text=_('Tempo estimado para produção dos pedidos na cozinha.')
    )
    opened_at = models.DateTimeField(
        _('Loja Aberta em'),
        null=True,
        blank=True,
        help_text=_('Data e hora em que a loja foi aberta manualmente nesta sessão.')
    )
    thermal_receipt_message = models.TextField(
        _('Mensagem do Cupom Térmico'),
        default='Agradecemos a sua preferência! Bom apetite e volte sempre!',
        blank=True,
        help_text=_('Mensagem impressa no rodapé dos cupons para clientes.')
    )

    class Meta:
        verbose_name = _('Loja')
        verbose_name_plural = _('Lojas')
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(Store, self.name, current_id=self.pk)
        super().save(*args, **kwargs)

    @property
    def full_address(self):
        parts = [self.street, self.number, self.neighborhood, self.city, self.state]
        return ", ".join([p for p in parts if p])

    def get_today_business_hour(self):
        """Retorna o horário de funcionamento cadastrado para o dia de hoje."""
        from django.utils import timezone
        today_weekday = timezone.localtime().weekday()
        return self.business_hours.filter(weekday=today_weekday).first()

    def get_today_hours_display(self) -> str:
        """Retorna a string de horários do dia, ex: '18:45 - 23:50' ou 'Fechado hoje'."""
        today_schedule = self.get_today_business_hour()
        if today_schedule and not today_schedule.is_closed and today_schedule.opening_time and today_schedule.closing_time:
            return f"{today_schedule.opening_time.strftime('%H:%M')} - {today_schedule.closing_time.strftime('%H:%M')}"
        return "18:00 - 23:30"

    def get_open_duration_minutes(self) -> int:
        """Calcula há quantos minutos a loja está aberta."""
        from django.utils import timezone
        if not self.is_currently_open():
            return 0
        now = timezone.now()
        if self.opened_at:
            return max(0, int((now - self.opened_at).total_seconds() // 60))
        # Se abriu pela grade horária
        today_schedule = self.get_today_business_hour()
        if today_schedule and today_schedule.opening_time:
            local_now = timezone.localtime(now)
            opening_dt = local_now.replace(hour=today_schedule.opening_time.hour, minute=today_schedule.opening_time.minute, second=0, microsecond=0)
            if local_now >= opening_dt:
                return max(0, int((local_now - opening_dt).total_seconds() // 60))
        return 0

    def is_currently_open(self, at_datetime=None) -> bool:
        """
        Calcula dinamicamente se a loja está aberta para receber pedidos.
        Leva em consideração:
        1. Se a loja está ativa na plataforma.
        2. Se os pedidos estão pausados temporariamente (botão de pausa).
        3. Abertura manual direta (is_open=True).
        4. Grade semanal de horários de funcionamento (BusinessHour).
        """
        from django.utils import timezone

        if not self.is_active or self.is_paused:
            return False

        # Se o lojista abriu manualmente, está aberta
        if self.is_open:
            return True

        # Verifica pela grade horária
        now = at_datetime or timezone.localtime()
        weekday = now.weekday()
        current_time = now.time()

        schedule = self.business_hours.filter(weekday=weekday, is_closed=False).first()
        if schedule and schedule.opening_time and schedule.closing_time:
            if schedule.opening_time <= current_time <= schedule.closing_time:
                return True

        return False

    @property
    def status_label(self) -> str:
        if not self.is_active:
            return "Inativa"
        if self.is_paused:
            return "Pausada"
        if self.is_currently_open():
            return "Aberto"
        return "Fechado"

    @property
    def whatsapp_link(self) -> str:
        """Gera link direto wa.me para o cliente entrar em contato com a loja."""
        import urllib.parse
        from whatsapp.services import clean_phone_number
        clean = clean_phone_number(self.whatsapp or '')
        if clean:
            msg = f"Olá, estava navegando no cardápio da {self.name} e gostaria de tirar uma dúvida!"
            return f"https://wa.me/{clean}?text={urllib.parse.quote(msg)}"
        return "#"

    def get_next_opening_text(self) -> str:
        """
        Retorna texto humanizado sobre a próxima reabertura ou previsão.
        Ex: 'Abre hoje às 18:00 (em cerca de 2 horas)', 'Abre amanhã às 18:00', etc.
        """
        from django.utils import timezone
        import datetime

        if self.is_paused:
            return "Pedidos pausados temporariamente pela cozinha. Voltaremos em instantes!"

        now = timezone.localtime()
        weekday = now.weekday()
        current_time = now.time()

        # 1. Verifica se abre mais tarde no próprio dia
        today_schedule = self.business_hours.filter(weekday=weekday, is_closed=False).first()
        if today_schedule and today_schedule.opening_time:
            if current_time < today_schedule.opening_time:
                open_dt = now.replace(
                    hour=today_schedule.opening_time.hour,
                    minute=today_schedule.opening_time.minute,
                    second=0,
                    microsecond=0
                )
                diff_sec = (open_dt - now).total_seconds()
                diff_min = int(diff_sec // 60)
                diff_hours = int(diff_min // 60)
                rem_min = diff_min % 60

                time_str = today_schedule.opening_time.strftime('%H:%M')
                if diff_hours > 0 and rem_min > 0:
                    time_hint = f"em cerca de {diff_hours}h {rem_min}min"
                elif diff_hours > 0:
                    time_hint = f"em cerca de {diff_hours}h"
                else:
                    time_hint = f"em cerca de {diff_min} minutos"
                return f"Abre hoje às {time_str} ({time_hint})"

        # 2. Verifica os próximos dias da semana
        for i in range(1, 8):
            next_day = (weekday + i) % 7
            next_schedule = self.business_hours.filter(weekday=next_day, is_closed=False).first()
            if next_schedule and next_schedule.opening_time:
                time_str = next_schedule.opening_time.strftime('%H:%M')
                day_name = "amanhã" if i == 1 else next_schedule.get_weekday_display().lower()
                return f"Abre {day_name} às {time_str}"

        return "Confira nossa grade de horários de funcionamento"


class BusinessHour(StoreBoundedModel):
    """
    Horário de funcionamento da loja por dia da semana.
    """
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='business_hours',
        verbose_name=_('Loja')
    )
    WEEKDAY_CHOICES = [
        (0, _('Segunda-feira')),
        (1, _('Terça-feira')),
        (2, _('Quarta-feira')),
        (3, _('Quinta-feira')),
        (4, _('Sexta-feira')),
        (5, _('Sábado')),
        (6, _('Domingo')),
    ]

    weekday = models.IntegerField(_('Dia da Semana'), choices=WEEKDAY_CHOICES)
    opening_time = models.TimeField(_('Horário de Abertura'), null=True, blank=True)
    closing_time = models.TimeField(_('Horário de Fechamento'), null=True, blank=True)
    is_closed = models.BooleanField(_('Fechado o Dia Todo'), default=False)

    class Meta:
        verbose_name = _('Horário de Funcionamento')
        verbose_name_plural = _('Horários de Funcionamento')
        unique_together = ('store', 'weekday')
        ordering = ['store', 'weekday']

    def __str__(self):
        day_name = dict(self.WEEKDAY_CHOICES).get(self.weekday, str(self.weekday))
        if self.is_closed:
            return f"{self.store.name} - {day_name}: Fechado"
        return f"{self.store.name} - {day_name}: {self.opening_time} às {self.closing_time}"
