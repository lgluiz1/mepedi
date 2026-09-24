from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.models import StoreBoundedModel, TimeStampedModel


class Category(StoreBoundedModel):
    """
    Categoria de produtos pertencente a uma loja específica.
    Exemplos: Hambúrgueres, Bebidas, Sobremesas, Combos.
    """
    name = models.CharField(
        _('Nome da Categoria'),
        max_length=100
    )
    description = models.TextField(
        _('Descrição'),
        blank=True,
        help_text=_('Breve descrição da categoria exibida no cardápio.')
    )
    order = models.PositiveIntegerField(
        _('Ordem de Exibição'),
        default=0,
        help_text=_('Menor número aparece primeiro no cardápio.')
    )
    is_active = models.BooleanField(
        _('Ativa'),
        default=True,
        help_text=_('Categorias inativas não aparecem no cardápio público.')
    )

    class Meta:
        verbose_name = _('Categoria')
        verbose_name_plural = _('Categorias')
        ordering = ['order', 'name']
        unique_together = ('store', 'name')

    def __str__(self):
        return f"{self.name} ({self.store.name})"


class Product(StoreBoundedModel):
    """
    Produto comercializado no cardápio da loja.
    """
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name=_('Categoria')
    )
    name = models.CharField(
        _('Nome do Produto'),
        max_length=150
    )
    description = models.TextField(
        _('Descrição'),
        blank=True,
        help_text=_('Ingredientes, tamanho e detalhes do produto.')
    )
    price = models.DecimalField(
        _('Preço Base (R$)'),
        max_digits=10,
        decimal_places=2,
        help_text=_('Valor de venda base do produto.')
    )
    image = models.ImageField(
        _('Foto do Produto'),
        upload_to='products/images/',
        blank=True,
        null=True
    )
    is_active = models.BooleanField(
        _('Disponível / Ativo'),
        default=True,
        help_text=_('Se desmarcado, fica marcado como esgotado/indisponível.')
    )
    order = models.PositiveIntegerField(
        _('Ordem de Exibição'),
        default=0
    )

    class Meta:
        verbose_name = _('Produto')
        verbose_name_plural = _('Produtos')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.name} - R$ {self.price:.2f} ({self.store.name})"

    def clean(self):
        super().clean()
        if self.category_id and self.store_id:
            if self.category.store_id != self.store_id:
                raise ValidationError({
                    'category': _('A categoria selecionada não pertence a esta loja.')
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class OptionGroup(StoreBoundedModel):
    """
    Grupo de opções vinculadas a um produto.
    Exemplos:
    - 'ADICIONAIS' (Bacon +R$5, Queijo +R$3, Ovo +R$2)
    - 'REMOVER INGREDIENTES' (Sem cebola, Sem tomate)
    - 'PONTO DA CARNE' (Ao ponto, Bem passado)
    """
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        verbose_name=_('Loja'),
        db_index=True,
        blank=True
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='option_groups',
        verbose_name=_('Produto')
    )
    name = models.CharField(
        _('Nome do Grupo'),
        max_length=100,
        help_text=_('Ex: Adicionais, Remover Ingredientes, Escolha o Molho')
    )
    description = models.CharField(
        _('Instrução / Descrição'),
        max_length=200,
        blank=True,
        help_text=_('Ex: Escolha até 3 adicionais')
    )
    min_options = models.PositiveIntegerField(
        _('Mínimo Obrigatório'),
        default=0,
        help_text=_('Quantidade mínima de itens que o cliente deve escolher. 0 = Opcional.')
    )
    max_options = models.PositiveIntegerField(
        _('Máximo Permitido'),
        default=1,
        help_text=_('Quantidade máxima de itens que o cliente pode escolher.')
    )
    is_required = models.BooleanField(
        _('Seleção Obrigatória'),
        default=False,
        help_text=_('Se marcado, o cliente deve escolher ao menos 1 item.')
    )
    order = models.PositiveIntegerField(
        _('Ordem'),
        default=0
    )

    class Meta:
        verbose_name = _('Grupo de Opções')
        verbose_name_plural = _('Grupos de Opções')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.product.name} - {self.name}"

    def clean(self):
        super().clean()
        if self.product_id:
            self.store_id = self.product.store_id
        if self.min_options > self.max_options:
            raise ValidationError({
                'min_options': _('A quantidade mínima não pode ser maior que o máximo permitido.')
            })
        if self.is_required and self.min_options == 0:
            self.min_options = 1

    def save(self, *args, **kwargs):
        if not self.store_id and self.product_id:
            self.store_id = self.product.store_id
        self.full_clean()
        super().save(*args, **kwargs)


class OptionItem(TimeStampedModel):
    """
    Item individual dentro de um grupo de opções.
    Pode ser um adicional com custo extra ou uma remoção/variação com custo zero (R$ 0,00).
    """
    option_group = models.ForeignKey(
        OptionGroup,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Grupo de Opções')
    )
    name = models.CharField(
        _('Nome da Opção'),
        max_length=100,
        help_text=_('Ex: Bacon, Queijo Extra, Sem Cebola, Ao Ponto')
    )
    price = models.DecimalField(
        _('Preço Adicional (R$)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Valor adicional cobrado. Utilize 0,00 para opções gratuitas ou remoções.')
    )
    is_available = models.BooleanField(
        _('Disponível'),
        default=True,
        help_text=_('Item disponível no momento.')
    )
    order = models.PositiveIntegerField(
        _('Ordem'),
        default=0
    )

    class Meta:
        verbose_name = _('Item de Opção')
        verbose_name_plural = _('Itens de Opção')
        ordering = ['order', 'name']

    def __str__(self):
        if self.price > 0:
            return f"{self.name} (+ R$ {self.price:.2f})"
        return self.name
