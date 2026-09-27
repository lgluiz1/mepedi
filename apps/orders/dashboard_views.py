import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from stores.models import Store
from subscriptions.decorators import feature_required
from .models import Order, Coupon


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
    import datetime
    current_store, active_stores = get_user_active_store(request.user, store_slug)

    # 1. Auto-cancela pedidos pendentes que não foram aceitos em até 10 minutos e estorna estoque
    from catalog.services import StockService
    cutoff_10m = timezone.now() - datetime.timedelta(minutes=10)
    expired_orders = Order.objects.filter(store=current_store, status=Order.STATUS_NEW, created_at__lt=cutoff_10m)
    for exp_order in expired_orders:
        exp_order.status = Order.STATUS_CANCELLED
        exp_order.save(update_fields=['status'])
        StockService.restore_stock(exp_order)

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

    # Contagem de tempo da loja aberta
    open_minutes = current_store.get_open_duration_minutes()
    if open_minutes >= 60:
        h = open_minutes // 60
        m = open_minutes % 60
        open_duration_str = f"{h:02d}h {m:02d}m"
    else:
        open_duration_str = f"{open_minutes:02d}m"

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'orders': orders_qs[:100],
        'counts': counts,
        'today_orders_count': today_orders.count(),
        'today_revenue': today_revenue,
        'is_currently_open': current_store.is_currently_open(),
        'open_duration_str': open_duration_str,
        'today_hours_display': current_store.get_today_hours_display(),
        'status_choices': Order.STATUS_CHOICES,
        'active_tab': 'orders',
    }
    return render(request, 'dashboard/orders.html', context)


@login_required(login_url='/painel/login/')
def merchant_store_settings_view(request, store_slug):
    """
    Gerenciamento de Identidade Visual, Horários de Funcionamento, Tempo de Preparo e Cupom Térmico.
    """
    from stores.models import BusinessHour
    import datetime

    current_store, active_stores = get_user_active_store(request.user, store_slug)
    success_msg = None
    error_msg = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_coupon':
            code = request.POST.get('coupon_code', '').strip().upper()
            disc_type = request.POST.get('discount_type', Coupon.DISCOUNT_PERCENTAGE)
            disc_val_raw = request.POST.get('discount_value', '0').strip().replace(',', '.')
            min_val_raw = request.POST.get('min_order_value', '0').strip().replace(',', '.')
            max_uses_raw = request.POST.get('max_uses', '').strip()
            valid_until_raw = request.POST.get('valid_until', '').strip()
            apply_to_delivery = request.POST.get('apply_to_delivery') == 'on'
            is_public = request.POST.get('is_public') == 'on'

            if not code or not disc_val_raw:
                error_msg = "Código e valor do desconto são obrigatórios."
            elif Coupon.objects.filter(store=current_store, code=code).exists():
                error_msg = f"Já existe um cupom com o código '{code}' cadastrado nesta loja."
            else:
                try:
                    disc_val = Decimal(disc_val_raw)
                    min_val = Decimal(min_val_raw) if min_val_raw else Decimal('0.00')
                    max_uses = int(max_uses_raw) if max_uses_raw else None
                    valid_until = None
                    if valid_until_raw:
                        from django.utils.dateparse import parse_datetime, parse_date
                        dt = parse_datetime(valid_until_raw)
                        if not dt:
                            d = parse_date(valid_until_raw)
                            if d:
                                dt = timezone.make_aware(datetime.datetime.combine(d, datetime.time.max))
                        valid_until = dt

                    Coupon.objects.create(
                        store=current_store,
                        code=code,
                        discount_type=disc_type,
                        discount_value=disc_val,
                        min_order_value=min_val,
                        apply_to_delivery=apply_to_delivery,
                        max_uses=max_uses,
                        valid_until=valid_until,
                        is_public=is_public,
                        is_active=True
                    )
                    success_msg = f'Cupom "{code}" criado com sucesso!'
                except Exception as e:
                    error_msg = f"Erro ao criar cupom: {e}"

        elif action == 'toggle_coupon':
            c_id = request.POST.get('coupon_id')
            coupon = get_object_or_404(Coupon, id=c_id, store=current_store)
            coupon.is_active = not coupon.is_active
            coupon.save(update_fields=['is_active'])
            status_txt = "ativado" if coupon.is_active else "pausado"
            success_msg = f'Cupom "{coupon.code}" {status_txt} com sucesso!'

        elif action == 'delete_coupon':
            c_id = request.POST.get('coupon_id')
            coupon = get_object_or_404(Coupon, id=c_id, store=current_store)
            c_code = coupon.code
            coupon.delete()
            success_msg = f'Cupom "{c_code}" excluído com sucesso!'

        else:
            # Salvar dados gerais da loja
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            whatsapp = request.POST.get('whatsapp', '').strip()
            phone = request.POST.get('phone', '').strip()
            allows_delivery = request.POST.get('allows_delivery') == 'on'
            allows_pickup = request.POST.get('allows_pickup') == 'on'
            time_min = request.POST.get('estimated_delivery_time_min', '30')
            time_max = request.POST.get('estimated_delivery_time_max', '60')
            prep_time = request.POST.get('preparation_time_minutes', '30')
            receipt_msg = request.POST.get('thermal_receipt_message', '').strip()

            # Endereço Comercial para Impressão do Cupom
            street = request.POST.get('street', '').strip()
            number = request.POST.get('number', '').strip()
            neighborhood = request.POST.get('neighborhood', '').strip()
            city = request.POST.get('city', '').strip()
            state = request.POST.get('state', '').strip().upper()
            postal_code = request.POST.get('postal_code', '').strip()

            # Valores Comerciais e Frete
            min_order_raw = request.POST.get('minimum_order_value', '0').strip().replace('R$', '').replace(' ', '').replace(',', '.')
            fixed_fee_raw = request.POST.get('fixed_delivery_fee', '0').strip().replace('R$', '').replace(' ', '').replace(',', '.')

            if not name or not whatsapp:
                error_msg = "Nome do estabelecimento e WhatsApp são campos obrigatórios."
            else:
                current_store.name = name
                current_store.description = description
                current_store.whatsapp = whatsapp
                current_store.phone = phone
                current_store.allows_delivery = allows_delivery
                current_store.allows_pickup = allows_pickup
                current_store.street = street
                current_store.number = number
                current_store.neighborhood = neighborhood
                current_store.city = city
                current_store.state = state
                current_store.postal_code = postal_code
                if receipt_msg:
                    current_store.thermal_receipt_message = receipt_msg

                try:
                    current_store.minimum_order_value = Decimal(min_order_raw) if min_order_raw else Decimal('0.00')
                except Exception:
                    pass

                try:
                    current_store.fixed_delivery_fee = Decimal(fixed_fee_raw) if fixed_fee_raw else Decimal('0.00')
                except Exception:
                    pass

                try:
                    current_store.estimated_delivery_time_min = int(time_min)
                    current_store.estimated_delivery_time_max = int(time_max)
                    current_store.preparation_time_minutes = int(prep_time)
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

                # Horários de Funcionamento por Dia da Semana (0 a 6)
                for day in range(7):
                    is_closed = request.POST.get(f'bh_{day}_closed') == 'on'
                    open_str = request.POST.get(f'bh_{day}_open', '').strip()
                    close_str = request.POST.get(f'bh_{day}_close', '').strip()

                    bh, _ = BusinessHour.objects.get_or_create(store=current_store, weekday=day)
                    bh.is_closed = is_closed
                    if not is_closed and open_str and close_str:
                        try:
                            bh.opening_time = datetime.datetime.strptime(open_str, '%H:%M').time()
                            bh.closing_time = datetime.datetime.strptime(close_str, '%H:%M').time()
                        except ValueError:
                            pass
                    bh.save()

                success_msg = "Configurações salvas com sucesso!"

    # Monta lista de dias da semana para o formulário
    from stores.models import BusinessHour
    existing_bhs = {bh.weekday: bh for bh in current_store.business_hours.all()}
    weekdays_data = []
    day_names = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]
    for w_day, w_name in day_names:
        bh_obj = existing_bhs.get(w_day)
        weekdays_data.append({
            'weekday': w_day,
            'name': w_name,
            'is_closed': bh_obj.is_closed if bh_obj else False,
            'opening_time': bh_obj.opening_time.strftime('%H:%M') if (bh_obj and bh_obj.opening_time) else '18:00',
            'closing_time': bh_obj.closing_time.strftime('%H:%M') if (bh_obj and bh_obj.closing_time) else '23:30',
        })

    coupons = Coupon.objects.filter(store=current_store).order_by('-created_at')

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'weekdays_data': weekdays_data,
        'coupons': coupons,
        'success_msg': success_msg,
        'error_msg': error_msg,
        'active_tab': 'settings',
    }
    return render(request, 'dashboard/settings.html', context)


@login_required(login_url='/painel/login/')
def merchant_products_view(request, store_slug):
    """
    Gestão completa do cardápio: cadastro e edição de produtos, código PDV,
    estoque unificado centralizado e valores promocionais (% OFF).
    """
    from catalog.models import Product, Category

    current_store, active_stores = get_user_active_store(request.user, store_slug)
    success_msg = None
    error_msg = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name', '').strip()
            code = request.POST.get('code', '').strip().upper() or None
            cat_id = request.POST.get('category')
            price_raw = request.POST.get('price', '').strip().replace(',', '.')
            description = request.POST.get('description', '').strip()
            is_active = request.POST.get('is_active') == 'on'
            track_stock = request.POST.get('track_stock') == 'on'
            stock_qty = int(request.POST.get('stock_quantity', 0) or 0)
            is_promotional = request.POST.get('is_promotional') == 'on'
            promo_price_raw = request.POST.get('promotional_price', '').strip().replace(',', '.')
            promo_price = Decimal(promo_price_raw) if (is_promotional and promo_price_raw) else None

            if not name or not cat_id or not price_raw:
                error_msg = "Por favor preencha nome, categoria e preço do produto."
            elif code and Product.objects.filter(store=current_store, code=code).exists():
                error_msg = f"O código '{code}' já está cadastrado em outro produto desta loja."
            else:
                category = get_object_or_404(Category, id=cat_id, store=current_store)
                try:
                    price = Decimal(price_raw)
                    product = Product(
                        store=current_store,
                        category=category,
                        name=name,
                        code=code,
                        price=price,
                        description=description,
                        is_active=is_active,
                        track_stock=track_stock,
                        stock_quantity=stock_qty,
                        is_promotional=is_promotional,
                        promotional_price=promo_price
                    )
                    if 'image' in request.FILES:
                        product.image = request.FILES['image']
                    product.save()

                    # Copiar grupos de opções de outro produto existente (se selecionado)
                    copy_from_id = request.POST.get('copy_options_from')
                    if copy_from_id and copy_from_id.isdigit():
                        source_prod = Product.objects.filter(id=int(copy_from_id), store=current_store).first()
                        if source_prod:
                            from catalog.options_service import clone_all_product_groups
                            cloned_g, cloned_i = clone_all_product_groups(source_prod, product)
                            success_msg = f'Produto "{name}" cadastrado com sucesso e {cloned_g} grupos de complementos ({cloned_i} itens) copiados de "{source_prod.name}"!'
                        else:
                            success_msg = f'Produto "{name}" cadastrado com sucesso!'
                    else:
                        success_msg = f'Produto "{name}" cadastrado com sucesso!'
                except Exception as e:
                    error_msg = f"Erro ao salvar produto: {e}"

        elif action == 'create_category':
            cat_name = request.POST.get('category_name', '').strip()
            if cat_name:
                from catalog.category_catalog import format_category_name_with_icon
                formatted_name = format_category_name_with_icon(cat_name)
                category, created = Category.objects.get_or_create(store=current_store, name=formatted_name)
                if created:
                    success_msg = f'Categoria "{category.name}" criada com sucesso com ícone automático!'
                else:
                    success_msg = f'Categoria "{category.name}" já está pronta e disponível!'
            else:
                error_msg = "Nome da categoria não pode ser vazio."

        elif action == 'edit':
            prod_id = request.POST.get('product_id')
            product = get_object_or_404(Product, id=prod_id, store=current_store)
            name = request.POST.get('name', '').strip()
            code = request.POST.get('code', '').strip().upper() or None
            cat_id = request.POST.get('category')
            price_raw = request.POST.get('price', '').strip().replace(',', '.')
            description = request.POST.get('description', '').strip()
            is_active = request.POST.get('is_active') == 'on'
            track_stock = request.POST.get('track_stock') == 'on'
            stock_qty = int(request.POST.get('stock_quantity', 0) or 0)
            is_promotional = request.POST.get('is_promotional') == 'on'
            promo_price_raw = request.POST.get('promotional_price', '').strip().replace(',', '.')
            promo_price = Decimal(promo_price_raw) if (is_promotional and promo_price_raw) else None

            if not name or not cat_id or not price_raw:
                error_msg = "Por favor preencha todos os campos obrigatórios."
            elif code and Product.objects.filter(store=current_store, code=code).exclude(id=product.id).exists():
                error_msg = f"O código '{code}' já está cadastrado em outro produto desta loja."
            else:
                category = get_object_or_404(Category, id=cat_id, store=current_store)
                try:
                    product.name = name
                    product.code = code
                    product.category = category
                    product.price = Decimal(price_raw)
                    product.description = description
                    product.is_active = is_active
                    product.track_stock = track_stock
                    product.stock_quantity = stock_qty
                    product.is_promotional = is_promotional
                    product.promotional_price = promo_price
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

    products = Product.objects.filter(store=current_store).select_related('category').prefetch_related('option_groups').order_by('category__name', 'order', 'name')
    categories = Category.objects.filter(store=current_store).order_by('name')
    products_with_options = [p for p in products if p.option_groups.all()]

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'products': products,
        'categories': categories,
        'products_with_options': products_with_options,
        'success_msg': success_msg,
        'error_msg': error_msg,
        'active_tab': 'products',
    }
    return render(request, 'dashboard/products.html', context)


@login_required(login_url='/painel/login/')
def merchant_product_options_view(request, store_slug, product_id):
    """
    Gestão de grupos de opções e adicionais (sabores, caldas, recheios, bordas, etc.)
    do produto selecionado pelo lojista com suporte a clonagem inteligente e importação rápida.
    """
    from catalog.models import Product, OptionGroup, OptionItem
    from catalog.options_service import (
        clone_option_group_to_product,
        clone_all_product_groups,
        bulk_create_option_items,
        get_store_template_groups
    )

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
                new_grp = OptionGroup.objects.create(
                    store=current_store,
                    product=product,
                    name=name,
                    description=description,
                    min_options=min_opt,
                    max_options=max_opt,
                    is_required=is_req
                )
                success_msg = f'Grupo "{name}" criado com sucesso!'

        # 2. Editar regras de um grupo existente (nome, descrição, min, max, obrigatório)
        elif action == 'edit_group':
            group_id = request.POST.get('group_id')
            grp = get_object_or_404(OptionGroup, id=group_id, product=product, store=current_store)
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
                grp.name = name
                grp.description = description
                grp.min_options = min_opt
                grp.max_options = max_opt
                grp.is_required = is_req
                grp.save()
                success_msg = f'Regras do grupo "{grp.name}" atualizadas com sucesso!'

        # 3. Clonar grupo específico de outro produto (com escolha de sabores e limites)
        elif action == 'clone_group':
            source_group_id = request.POST.get('source_group_id')
            source_grp = get_object_or_404(OptionGroup, id=source_group_id, store=current_store)
            new_name = request.POST.get('name', '').strip() or source_grp.name
            description = request.POST.get('description', '').strip() or source_grp.description
            min_opt = int(request.POST.get('min_options', source_grp.min_options))
            max_opt = int(request.POST.get('max_options', source_grp.max_options))
            is_req = request.POST.get('is_required') == 'on' or min_opt > 0
            selected_items = request.POST.getlist('selected_items')

            try:
                cloned = clone_option_group_to_product(
                    source_group=source_grp,
                    target_product=product,
                    new_name=new_name,
                    description=description,
                    min_options=min_opt,
                    max_options=max_opt,
                    is_required=is_req,
                    selected_item_ids=selected_items if selected_items else None
                )
                success_msg = f'Grupo "{cloned.name}" copiado com sucesso com {cloned.items.count()} opções importadas!'
            except Exception as e:
                error_msg = f"Erro ao copiar grupo: {e}"

        # 4. Clonar TODOS os grupos de outro produto de uma só vez
        elif action == 'clone_all_groups':
            source_prod_id = request.POST.get('source_product_id')
            source_prod = get_object_or_404(Product, id=source_prod_id, store=current_store)
            try:
                grps_cnt, items_cnt = clone_all_product_groups(source_prod, product)
                success_msg = f'Todos os {grps_cnt} grupos ({items_cnt} itens) de "{source_prod.name}" foram copiados com sucesso!'
            except Exception as e:
                error_msg = f"Erro ao clonar grupos do produto: {e}"

        # 5. Adicionar sabores/itens em massa a partir de lista colada
        elif action == 'bulk_create_items':
            group_id = request.POST.get('group_id')
            grp = get_object_or_404(OptionGroup, id=group_id, product=product, store=current_store)
            items_text = request.POST.get('items_text', '').strip()
            if not items_text:
                error_msg = "Insira ou cole a lista de sabores/itens antes de salvar."
            else:
                try:
                    added_count = bulk_create_option_items(grp, items_text)
                    success_msg = f'{added_count} opções/sabores adicionados com sucesso ao grupo "{grp.name}"!'
                except Exception as e:
                    error_msg = f"Erro ao adicionar itens em massa: {e}"

        # 6. Excluir grupo de opções
        elif action == 'delete_group':
            group_id = request.POST.get('group_id')
            grp = get_object_or_404(OptionGroup, id=group_id, product=product, store=current_store)
            grp_name = grp.name
            grp.delete()
            success_msg = f'Grupo "{grp_name}" excluído!'

        # 7. Adicionar item/sabor individual ao grupo
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

        # 8. Alternar disponibilidade (Disponível <-> Esgotado) com 1 clique!
        elif action == 'toggle_item':
            item_id = request.POST.get('item_id')
            item = get_object_or_404(OptionItem, id=item_id, option_group__product=product)
            item.is_available = not item.is_available
            item.save()
            status_text = "disponível" if item.is_available else "marcado como esgotado"
            success_msg = f'Sabor/Opção "{item.name}" {status_text}!'

        # 9. Excluir item
        elif action == 'delete_item':
            item_id = request.POST.get('item_id')
            item = get_object_or_404(OptionItem, id=item_id, option_group__product=product)
            item_name = item.name
            item.delete()
            success_msg = f'Opção "{item_name}" excluída!'

    option_groups = OptionGroup.objects.filter(product=product).prefetch_related('items').order_by('order', 'id')
    template_groups = get_store_template_groups(current_store, product)
    other_products_with_groups = Product.objects.filter(
        store=current_store, option_groups__isnull=False
    ).exclude(id=product.id).distinct().prefetch_related('option_groups__items').order_by('name')

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'product': product,
        'option_groups': option_groups,
        'template_groups': template_groups,
        'template_groups_json': json.dumps(template_groups),
        'other_products_with_groups': other_products_with_groups,
        'success_msg': success_msg,
        'error_msg': error_msg,
        'active_tab': 'products',
    }
    return render(request, 'dashboard/product_options.html', context)


@login_required(login_url='/painel/login/')
@feature_required('pdv')
def merchant_pos_view(request, store_slug):
    """
    Ponto de Venda (PDV Balcão) integrado para o lojista com baixa no mesmo estoque centralizado.
    Suporta busca rápida por nome/código, opções/adicionais, cupons e impressão térmica (58mm/80mm).
    """
    import json
    from catalog.models import Category, Product
    from orders.models import Order, Coupon

    current_store, active_stores = get_user_active_store(request.user, store_slug)

    categories = Category.objects.filter(store=current_store).prefetch_related(
        'products__option_groups__items'
    ).order_by('name')

    # Prepara JSON do catálogo do PDV com código, estoque e preços promocionais
    pos_catalog = {}
    for cat in categories:
        for prod in cat.products.filter(is_active=True):
            pos_catalog[prod.id] = {
                'id': prod.id,
                'code': prod.code or '',
                'name': prod.name,
                'description': prod.description or '',
                'category_id': cat.id,
                'category_name': cat.name,
                'base_price': float(prod.price),
                'current_price': float(prod.current_price),
                'is_promotional': prod.is_promotional,
                'promotional_price': float(prod.promotional_price) if prod.promotional_price else None,
                'discount_percent': prod.discount_percent,
                'track_stock': prod.track_stock,
                'stock_quantity': prod.stock_quantity,
                'is_in_stock': prod.is_in_stock,
                'image_url': prod.image.url if prod.image else None,
                'option_groups': [
                    {
                        'id': og.id,
                        'name': og.name,
                        'description': og.description,
                        'min_options': og.min_options,
                        'max_options': og.max_options,
                        'is_required': og.is_required,
                        'items': [
                            {
                                'id': item.id,
                                'name': item.name,
                                'price': float(item.price),
                                'is_available': item.is_available,
                            }
                            for item in og.items.filter(is_available=True).order_by('order', 'name')
                        ]
                    }
                    for og in prod.option_groups.all()
                ]
            }

    # Últimos pedidos do PDV realizados hoje
    today = timezone.localdate()
    today_pos_orders = Order.objects.filter(
        store=current_store,
        origin=Order.ORIGIN_PDV,
        created_at__date=today
    ).prefetch_related('items__selected_options').order_by('-created_at')[:20]

    # Cupons ativos da loja
    active_coupons = Coupon.objects.filter(store=current_store, is_active=True).order_by('code')

    context = {
        'store': current_store,
        'user_stores': active_stores,
        'categories': categories,
        'pos_catalog_json': json.dumps(pos_catalog),
        'today_pos_orders': today_pos_orders,
        'active_coupons': active_coupons,
        'active_tab': 'pos',
    }
    return render(request, 'dashboard/pos.html', context)



