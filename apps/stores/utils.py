import re
from django.utils.text import slugify


def generate_unique_slug(model_class, title, current_id=None, slug_field_name='slug'):
    """
    Gera um slug único a partir de um título para a classe de modelo informada.
    Se 'loja-do-luiz' já existir, testa 'loja-do-luiz-2', 'loja-do-luiz-3', etc.
    """
    origin_slug = slugify(title)
    if not origin_slug:
        origin_slug = "loja"

    unique_slug = origin_slug
    counter = 1

    qs = model_class.objects.all()
    if current_id:
        qs = qs.exclude(id=current_id)

    while qs.filter(**{slug_field_name: unique_slug}).exists():
        counter += 1
        unique_slug = f"{origin_slug}-{counter}"

    return unique_slug
