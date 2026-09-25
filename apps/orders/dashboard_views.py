from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from stores.models import Store
from .models import Order


def merchant_login_view(request):
    """
    Tela de login exclusiva para o painel de pedidos do lojista.
    """
    if request.user.is_authenticated:
        return redirect('merchant_dashboard_root')

    error = None
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')

        if not email or not password:
            error = "Por favor, preencha o e-mail e a senha."
        else:
            user = authenticate(request, username=email, password=password)
            if user:
                login(request, user)
                next_url = request.GET.get('next', '/painel/')
                return redirect(next_url)
            else:
                error = "E-mail ou senha inválidos. Tente novamente."

    return render(request, 'dashboard/login.html', {'error': error})


def merchant_logout_view(request):
    """
    Encerra a sessão do lojista e redireciona para a tela de login.
    """
    logout(request)
    return redirect('merchant_login')


@login_required(login_url='/painel/login/')
def merchant_dashboard_root_view(request):
    """
    Ponto de entrada do painel: redireciona para a primeira loja do lojista.
    """
    user_memberships = request.user.memberships.filter(is_active=True).select_related('store')
    active_stores = [m.store for m in user_memberships if m.store.is_active]

    if not active_stores:
        return render(request, 'dashboard/no_store.html')

    return redirect('merchant_dashboard_store', store_slug=active_stores[0].slug)


def get_user_active_store(user, store_slug):
    """
    Helper com validação multi-tenant para obter a loja ativa do lojista autenticado.
    """
    user_memberships = user.memberships.filter(is_active=True).select_related('store')
    active_stores = [m.store for m in user_memberships if m.store.is_active]
    current_store = next((s for s in active_stores if s.slug == store_slug), None)
    if not current_store:
        raise PermissionDenied("Você não possui permissão para acessar esta loja.")
    return current_store, active_stores


@login_required(login_url='/painel/login/')
def merchant_dashboard_store_view(request, store_slug):
    """
    Painel de controle e acompanhamento de pedidos em tempo real para a loja selecionada.
    """
    current_store, active_stores = get_user_active_store(request.user, store_slug)

    orders_qs = Order.objects.filter(store=current_store).prefetch_related(
        'items__selected_options', 'customer'
    ).order_by('-created_at')

    today = timezone.localdate()
    today_orders = orders_qs.filter(created_at__date=today)
    today_revenue = sum(
        (o.total for o in today_orders if o.status != 'CANCELADO'),
        Decimal('0.00')
    )

    counts = {
        'ALL': orders_qs.count(),
        'NOVO': orders_qs.filter(status='NOVO').count(),
        'ACEITO': orders_qs.filter(status='ACEITO').count(),
        'EM_PREPARACAO': orders_qs.filter(status='EM_PREPARACAO').count(),
        'PRONTO': orders_qs.filter(status='PRONTO').count(),
        'SAIU_PARA_ENTREGA': orders_qs.filter(status='SAIU_PARA_ENTREGA').count(),
        'CONCLUIDO': orders_qs.filter(status='CONCLUIDO').count(),
        'CANCELADO': orders_qs.filter(status='CANCELADO').count(),
    }

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'orders': orders_qs[:100],
        'counts': counts,
        'today_orders_count': today_orders.count(),
        'today_revenue': today_revenue,
        'is_currently_open': current_store.is_currently_open(),
        'status_choices': Order.STATUS_CHOICES,
        'active_tab': 'orders',
    }
    return render(request, 'dashboard/orders.html', context)


@login_required(login_url='/painel/login/')
def merchant_store_settings_view(request, store_slug):
    """
    Gerenciamento de Identidade Visual (Logo e Capa/Banner) e configurações da loja.
    """
    current_store, active_stores = get_user_active_store(request.user, store_slug)
    success_msg = None
    error_msg = None

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        whatsapp = request.POST.get('whatsapp', '').strip()
        phone = request.POST.get('phone', '').strip()
        allows_delivery = request.POST.get('allows_delivery') == 'on'
        allows_pickup = request.POST.get('allows_pickup') == 'on'
        time_min = request.POST.get('estimated_delivery_time_min', '30')
        time_max = request.POST.get('estimated_delivery_time_max', '60')

        if not name or not whatsapp:
            error_msg = "Nome do estabelecimento e WhatsApp são campos obrigatórios."
        else:
            current_store.name = name
            current_store.description = description
            current_store.whatsapp = whatsapp
            current_store.phone = phone
            current_store.allows_delivery = allows_delivery
            current_store.allows_pickup = allows_pickup
            try:
                current_store.estimated_delivery_time_min = int(time_min)
                current_store.estimated_delivery_time_max = int(time_max)
            except ValueError:
                pass

            # Upload de Logotipo
            if 'logo' in request.FILES:
                current_store.logo = request.FILES['logo']

            # Upload de Capa / Banner de Fundo
            if 'banner' in request.FILES:
                current_store.banner = request.FILES['banner']

            # Remoção voluntária de Logo ou Banner
            if request.POST.get('remove_logo') == '1':
                current_store.logo = None
            if request.POST.get('remove_banner') == '1':
                current_store.banner = None

            current_store.save()
            success_msg = "Configurações e identidade visual da loja salvas com sucesso!"

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'success_msg': success_msg,
        'error_msg': error_msg,
        'active_tab': 'settings',
    }
    return render(request, 'dashboard/settings.html', context)


@login_required(login_url='/painel/login/')
def merchant_products_view(request, store_slug):
    """
    Gestão completa do cardápio: cadastro e edição de produtos com fotos.
    """
    from catalog.models import Product, Category

    current_store, active_stores = get_user_active_store(request.user, store_slug)
    success_msg = None
    error_msg = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name', '').strip()
            cat_id = request.POST.get('category')
            price_raw = request.POST.get('price', '').strip().replace(',', '.')
            description = request.POST.get('description', '').strip()
            is_active = request.POST.get('is_active') == 'on'

            if not name or not cat_id or not price_raw:
                error_msg = "Por favor preencha nome, categoria e preço do produto."
            else:
                category = get_object_or_404(Category, id=cat_id, store=current_store)
                try:
                    price = Decimal(price_raw)
                    product = Product(
                        store=current_store,
                        category=category,
                        name=name,
                        price=price,
                        description=description,
                        is_active=is_active
                    )
                    if 'image' in request.FILES:
                        product.image = request.FILES['image']
                    product.save()
                    success_msg = f'Produto "{name}" cadastrado com sucesso!'
                except Exception as e:
                    error_msg = f"Erro ao salvar produto: {e}"

        elif action == 'create_category':
            cat_name = request.POST.get('category_name', '').strip()
            if cat_name:
                Category.objects.get_or_create(store=current_store, name=cat_name)
                success_msg = f'Categoria "{cat_name}" criada com sucesso!'
            else:
                error_msg = "Nome da categoria não pode ser vazio."

        elif action == 'edit':
            prod_id = request.POST.get('product_id')
            product = get_object_or_404(Product, id=prod_id, store=current_store)
            name = request.POST.get('name', '').strip()
            cat_id = request.POST.get('category')
            price_raw = request.POST.get('price', '').strip().replace(',', '.')
            description = request.POST.get('description', '').strip()
            is_active = request.POST.get('is_active') == 'on'

            if not name or not cat_id or not price_raw:
                error_msg = "Por favor preencha todos os campos obrigatórios."
            else:
                category = get_object_or_404(Category, id=cat_id, store=current_store)
                try:
                    product.name = name
                    product.category = category
                    product.price = Decimal(price_raw)
                    product.description = description
                    product.is_active = is_active
                    if 'image' in request.FILES:
                        product.image = request.FILES['image']
                    elif request.POST.get('remove_image') == '1':
                        product.image = None
                    product.save()
                    success_msg = f'Produto "{name}" atualizado com sucesso!'
                except Exception as e:
                    error_msg = f"Erro ao atualizar produto: {e}"

        elif action == 'toggle':
            prod_id = request.POST.get('product_id')
            product = get_object_or_404(Product, id=prod_id, store=current_store)
            product.is_active = not product.is_active
            product.save()
            status_text = "ativado" if product.is_active else "pausado"
            success_msg = f'Produto "{product.name}" {status_text}!'

        elif action == 'delete':
            prod_id = request.POST.get('product_id')
            product = get_object_or_404(Product, id=prod_id, store=current_store)
            prod_name = product.name
            product.delete()
            success_msg = f'Produto "{prod_name}" removido com sucesso!'

    products = Product.objects.filter(store=current_store).select_related('category').order_by('category__name', 'order', 'name')
    categories = Category.objects.filter(store=current_store).order_by('name')

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'products': products,
        'categories': categories,
        'success_msg': success_msg,
        'error_msg': error_msg,
        'active_tab': 'products',
    }
    return render(request, 'dashboard/products.html', context)


@login_required(login_url='/painel/login/')
def merchant_product_options_view(request, store_slug, product_id):
    """
    Gestão de grupos de opções e adicionais (sabores, caldas, recheios, bordas, etc.)
    do produto selecionado pelo lojista.
    """
    from catalog.models import Product, OptionGroup, OptionItem

    current_store, active_stores = get_user_active_store(request.user, store_slug)
    product = get_object_or_404(Product, id=product_id, store=current_store)
    success_msg = None
    error_msg = None

    if request.method == 'POST':
        action = request.POST.get('action')

        # 1. Criar novo grupo de opções (ex: "Escolha até 4 Sabores")
        if action == 'create_group':
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            min_opt = int(request.POST.get('min_options', 0))
            max_opt = int(request.POST.get('max_options', 1))
            is_req = request.POST.get('is_required') == 'on' or min_opt > 0

            if not name:
                error_msg = "Nome do grupo de opções é obrigatório."
            elif min_opt > max_opt:
                error_msg = "A quantidade mínima não pode ser maior que o máximo permitido."
            else:
                OptionGroup.objects.create(
                    store=current_store,
                    product=product,
                    name=name,
                    description=description,
                    min_options=min_opt,
                    max_options=max_opt,
                    is_required=is_req
                )
                success_msg = f'Grupo "{name}" criado com sucesso!'

        # 2. Excluir grupo de opções
        elif action == 'delete_group':
            group_id = request.POST.get('group_id')
            grp = get_object_or_404(OptionGroup, id=group_id, product=product, store=current_store)
            grp_name = grp.name
            grp.delete()
            success_msg = f'Grupo "{grp_name}" excluído!'

        # 3. Adicionar item/sabor ao grupo
        elif action == 'create_item':
            group_id = request.POST.get('group_id')
            grp = get_object_or_404(OptionGroup, id=group_id, product=product, store=current_store)
            name = request.POST.get('name', '').strip()
            price_raw = request.POST.get('price', '0').strip().replace(',', '.')
            is_avail = request.POST.get('is_available') == 'on'

            if not name:
                error_msg = "Nome da opção / sabor é obrigatório."
            else:
                try:
                    price = Decimal(price_raw)
                    OptionItem.objects.create(
                        option_group=grp,
                        name=name,
                        price=price,
                        is_available=is_avail
                    )
                    success_msg = f'Opção "{name}" adicionada ao grupo "{grp.name}"!'
                except Exception as e:
                    error_msg = f"Erro ao adicionar opção: {e}"

        # 4. Alternar disponibilidade (Disponível <-> Esgotado) com 1 clique!
        elif action == 'toggle_item':
            item_id = request.POST.get('item_id')
            item = get_object_or_404(OptionItem, id=item_id, option_group__product=product)
            item.is_available = not item.is_available
            item.save()
            status_text = "disponível" if item.is_available else "marcado como esgotado"
            success_msg = f'Sabor/Opção "{item.name}" {status_text}!'

        # 5. Excluir item
        elif action == 'delete_item':
            item_id = request.POST.get('item_id')
            item = get_object_or_404(OptionItem, id=item_id, option_group__product=product)
            item_name = item.name
            item.delete()
            success_msg = f'Opção "{item_name}" excluída!'

    option_groups = OptionGroup.objects.filter(product=product).prefetch_related('items').order_by('order', 'id')

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'product': product,
        'option_groups': option_groups,
        'success_msg': success_msg,
        'error_msg': error_msg,
        'active_tab': 'products',
    }
    return render(request, 'dashboard/product_options.html', context)


