import datetime
from decimal import Decimal
from typing import Dict, Any, Tuple
from django.utils import timezone
from django.db.models import (
    Sum, Count, Avg, F, Q, Max, Min,
    ExpressionWrapper, DurationField, IntegerField
)
from django.db.models.functions import TruncDate, TruncHour, ExtractHour

from stores.models import Store
from orders.models import Order, OrderItem
from catalog.models import Product, StockMovement
from .models import TrafficVisit, TrackableLink, AnalyticsEvent


def parse_date_period(
    period: str = '30d',
    start_date_str: str = None,
    end_date_str: str = None
) -> Tuple[datetime.datetime, datetime.datetime, str]:
    """
    Calcula o intervalo de início e fim no fuso horário do sistema / loja.
    Retorna (start_datetime, end_datetime, period_label).
    """
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    period = (period or '30d').lower()

    if period == 'hoje':
        start_dt = today_start
        end_dt = today_end
        label = 'Hoje'
    elif period == 'ontem':
        yesterday = today_start - datetime.timedelta(days=1)
        start_dt = yesterday
        end_dt = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = 'Ontem'
    elif period == '7d':
        start_dt = (today_start - datetime.timedelta(days=6))
        end_dt = today_end
        label = 'Últimos 7 dias'
    elif period == '90d':
        start_dt = (today_start - datetime.timedelta(days=89))
        end_dt = today_end
        label = 'Últimos 90 dias'
    elif period == 'custom' and start_date_str and end_date_str:
        try:
            s_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            e_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            start_dt = timezone.make_aware(datetime.datetime.combine(s_date, datetime.time.min))
            end_dt = timezone.make_aware(datetime.datetime.combine(e_date, datetime.time.max))
            label = f"{s_date.strftime('%d/%m/%Y')} até {e_date.strftime('%d/%m/%Y')}"
        except Exception:
            start_dt = (today_start - datetime.timedelta(days=29))
            end_dt = today_end
            label = 'Últimos 30 dias'
    else:  # '30d' default
        start_dt = (today_start - datetime.timedelta(days=29))
        end_dt = today_end
        label = 'Últimos 30 dias'

    return start_dt, end_dt, label


class AnalyticsQueryService:
    """
    Serviço central de leitura, agregação e consolidação analítica.
    Todas as consultas respeitam rigorosamente o multi-tenant (store=store).
    """

    def __init__(self, store: Store, start_dt: datetime.datetime, end_dt: datetime.datetime, period_label: str):
        self.store = store
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.period_label = period_label

    def get_all_metrics(self) -> Dict[str, Any]:
        """
        Consolida as métricas completas para renderização no dashboard.
        """
        return {
            'period_label': self.period_label,
            'start_dt': self.start_dt,
            'end_dt': self.end_dt,
            'overview': self.get_overview_metrics(),
            'traffic': self.get_traffic_metrics(),
            'sales': self.get_sales_metrics(),
            'products': self.get_product_metrics(),
            'operations': self.get_operations_metrics(),
            'pos': self.get_pos_metrics(),
            'stock': self.get_stock_metrics(),
        }

    # =========================================================================
    # 1. VISÃO GERAL
    # =========================================================================
    def get_overview_metrics(self) -> Dict[str, Any]:
        orders_all = Order.objects.filter(
            store=self.store,
            created_at__range=(self.start_dt, self.end_dt)
        )
        total_orders_count = orders_all.count()
        cancelled_orders = orders_all.filter(status=Order.STATUS_CANCELLED)
        cancelled_count = cancelled_orders.count()

        valid_orders = orders_all.exclude(status=Order.STATUS_CANCELLED)
        valid_orders_count = valid_orders.count()

        revenue_agg = valid_orders.aggregate(total_rev=Sum('total'))
        total_revenue = revenue_agg['total_rev'] or Decimal('0.00')

        ticket_medio = (total_revenue / valid_orders_count) if valid_orders_count > 0 else Decimal('0.00')

        cancel_rate = (cancelled_count / total_orders_count * 100) if total_orders_count > 0 else 0.0

        # Segmentação Online x PDV
        online_valid = valid_orders.filter(origin=Order.ORIGIN_ONLINE)
        online_orders_count = online_valid.count()
        online_revenue = online_valid.aggregate(rev=Sum('total'))['rev'] or Decimal('0.00')

        pdv_valid = valid_orders.filter(origin=Order.ORIGIN_PDV)
        pdv_orders_count = pdv_valid.count()
        pdv_revenue = pdv_valid.aggregate(rev=Sum('total'))['rev'] or Decimal('0.00')

        # Tráfego
        visits_qs = TrafficVisit.objects.filter(
            store=self.store,
            created_at__range=(self.start_dt, self.end_dt)
        )
        total_visits = visits_qs.count()
        unique_sessions = visits_qs.values('session_id').distinct().count()

        conversion_rate = (online_orders_count / total_visits * 100) if total_visits > 0 else 0.0

        # Série temporal diária para os gráficos
        daily_revenue = list(
            valid_orders.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(
                day_total=Sum('total'),
                orders=Count('id'),
                online_rev=Sum('total', filter=Q(origin=Order.ORIGIN_ONLINE)),
                pdv_rev=Sum('total', filter=Q(origin=Order.ORIGIN_PDV)),
                online_orders=Count('id', filter=Q(origin=Order.ORIGIN_ONLINE)),
                pdv_orders=Count('id', filter=Q(origin=Order.ORIGIN_PDV))
            )
            .order_by('day')
        )

        daily_visits = list(
            visits_qs.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(visits=Count('id'))
            .order_by('day')
        )

        visits_by_day = {item['day'].strftime('%Y-%m-%d'): item['visits'] for item in daily_visits if item['day']}

        # Mescla dias para gerar timeline sincronizada
        timeline = []
        for d in daily_revenue:
            day_str = d['day'].strftime('%Y-%m-%d') if d['day'] else ''
            timeline.append({
                'date': day_str,
                'label': d['day'].strftime('%d/%m') if d['day'] else '',
                'total': float(d['day_total'] or 0),
                'orders': d['orders'] or 0,
                'online_rev': float(d['online_rev'] or 0),
                'pdv_rev': float(d['pdv_rev'] or 0),
                'online_orders': d['online_orders'] or 0,
                'pdv_orders': d['pdv_orders'] or 0,
                'visits': visits_by_day.get(day_str, 0)
            })

        return {
            'total_revenue': total_revenue,
            'total_orders': total_orders_count,
            'valid_orders': valid_orders_count,
            'cancelled_orders': cancelled_count,
            'cancel_rate': round(cancel_rate, 1),
            'ticket_medio': ticket_medio,
            'total_visits': total_visits,
            'unique_sessions': unique_sessions,
            'conversion_rate': round(conversion_rate, 2),
            'online_orders_count': online_orders_count,
            'online_revenue': online_revenue,
            'pdv_orders_count': pdv_orders_count,
            'pdv_revenue': pdv_revenue,
            'timeline': timeline,
        }

    # =========================================================================
    # 2. TRÁFEGO & FUNIL & LINKS RASTREÁVEIS
    # =========================================================================
    def get_traffic_metrics(self) -> Dict[str, Any]:
        visits_qs = TrafficVisit.objects.filter(
            store=self.store,
            created_at__range=(self.start_dt, self.end_dt)
        )
        total_visits = visits_qs.count()

        # Origens agrupadas por utm_source
        sources_agg = list(
            visits_qs.values('utm_source')
            .annotate(visits=Count('id'))
            .order_by('-visits')
        )

        # Trata fontes nulas/vazias como "Direto / Sem UTM" ou pelo Referrer
        categorized_sources = {}
        for s in visits_qs:
            src = s.display_source
            categorized_sources[src] = categorized_sources.get(src, 0) + 1

        top_sources = [
            {'source': k, 'visits': v, 'percent': round(v / total_visits * 100, 1) if total_visits > 0 else 0}
            for k, v in sorted(categorized_sources.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        # Campanhas
        top_campaigns = list(
            visits_qs.exclude(utm_campaign__isnull=True).exclude(utm_campaign='')
            .values('utm_campaign')
            .annotate(visits=Count('id'))
            .order_by('-visits')[:8]
        )

        # Links rastreáveis gerenciados pelo lojista
        trackable_links = TrackableLink.objects.filter(store=self.store, is_active=True).order_by('-created_at')
        links_data = []
        for link in trackable_links:
            # Visitas capturadas com essa origem e campanha
            link_visits = visits_qs.filter(
                utm_source__iexact=link.utm_source,
                utm_campaign__iexact=link.utm_campaign
            ).count()

            # Pedidos gerados com essa campanha via AnalyticsEvent
            events_orders = AnalyticsEvent.objects.filter(
                store=self.store,
                event_type=AnalyticsEvent.EVENT_ORDER_CREATED,
                created_at__range=(self.start_dt, self.end_dt),
                metadata__utm_source__iexact=link.utm_source,
                metadata__utm_campaign__iexact=link.utm_campaign
            ).count()

            # Faturamento estimado desses pedidos
            link_orders_qs = Order.objects.filter(
                analytics_events__event_type=AnalyticsEvent.EVENT_ORDER_CREATED,
                analytics_events__metadata__utm_source__iexact=link.utm_source,
                analytics_events__metadata__utm_campaign__iexact=link.utm_campaign,
                created_at__range=(self.start_dt, self.end_dt)
            ).exclude(status=Order.STATUS_CANCELLED).distinct()
            
            link_rev = link_orders_qs.aggregate(rev=Sum('total'))['rev'] or Decimal('0.00')

            clicks = max(link.clicks_count, link_visits)
            conv = (events_orders / clicks * 100) if clicks > 0 else 0.0

            links_data.append({
                'id': link.id,
                'name': link.name,
                'utm_source': link.utm_source,
                'utm_campaign': link.utm_campaign,
                'slug_code': link.slug_code,
                'url': link.build_url(),
                'clicks': clicks,
                'orders': events_orders,
                'revenue': link_rev,
                'conversion': round(conv, 2)
            })

        # Funil de Conversão (Eventos)
        events_qs = AnalyticsEvent.objects.filter(
            store=self.store,
            created_at__range=(self.start_dt, self.end_dt)
        )
        page_views = events_qs.filter(event_type=AnalyticsEvent.EVENT_PAGE_VIEW).count() or total_visits
        product_views = events_qs.filter(event_type=AnalyticsEvent.EVENT_PRODUCT_VIEW).count()
        cart_adds = events_qs.filter(event_type=AnalyticsEvent.EVENT_ADD_TO_CART).count()
        checkout_starts = events_qs.filter(event_type=AnalyticsEvent.EVENT_CHECKOUT_STARTED).count()
        orders_created = Order.objects.filter(
            store=self.store,
            origin=Order.ORIGIN_ONLINE,
            created_at__range=(self.start_dt, self.end_dt)
        ).count()
        orders_completed = Order.objects.filter(
            store=self.store,
            origin=Order.ORIGIN_ONLINE,
            status=Order.STATUS_COMPLETED,
            created_at__range=(self.start_dt, self.end_dt)
        ).count()

        funnel_steps = [
            {'name': '1. Visitas ao Cardápio', 'count': page_views, 'color': '#6366f1'},
            {'name': '2. Produtos Visualizados', 'count': product_views, 'color': '#8b5cf6'},
            {'name': '3. Itens Adicionados ao Carrinho', 'count': cart_adds, 'color': '#ec4899'},
            {'name': '4. Checkout Iniciado', 'count': checkout_starts, 'color': '#f59e0b'},
            {'name': '5. Pedidos Concluídos', 'count': orders_completed or orders_created, 'color': '#10b981'},
        ]

        # Calcula taxas entre etapas
        for i, step in enumerate(funnel_steps):
            if i == 0:
                step['pct_from_prev'] = 100.0
                step['pct_from_top'] = 100.0
            else:
                prev = funnel_steps[i - 1]['count']
                step['pct_from_prev'] = round((step['count'] / prev * 100), 1) if prev > 0 else 0.0
                top = funnel_steps[0]['count']
                step['pct_from_top'] = round((step['count'] / top * 100), 1) if top > 0 else 0.0

        return {
            'total_visits': total_visits,
            'top_sources': top_sources,
            'top_campaigns': top_campaigns,
            'links': links_data,
            'funnel_steps': funnel_steps,
        }

    # =========================================================================
    # 3. VENDAS & FORMAS DE PAGAMENTO & HORÁRIOS
    # =========================================================================
    def get_sales_metrics(self) -> Dict[str, Any]:
        orders_qs = Order.objects.filter(
            store=self.store,
            created_at__range=(self.start_dt, self.end_dt)
        )
        valid_orders = orders_qs.exclude(status=Order.STATUS_CANCELLED)
        total_revenue = valid_orders.aggregate(rev=Sum('total'))['rev'] or Decimal('0.00')
        total_subtotal = valid_orders.aggregate(s=Sum('subtotal'))['s'] or Decimal('0.00')
        total_delivery = valid_orders.aggregate(d=Sum('delivery_fee'))['d'] or Decimal('0.00')
        total_discounts = valid_orders.aggregate(disc=Sum('discount'))['disc'] or Decimal('0.00')

        # Formas de pagamento
        payment_labels = dict(Order.PAYMENT_CHOICES)
        payment_stats = list(
            valid_orders.values('payment_method')
            .annotate(count=Count('id'), total_amount=Sum('total'))
            .order_by('-total_amount')
        )
        for p in payment_stats:
            p['label'] = payment_labels.get(p['payment_method'], p['payment_method'])
            p['total'] = float(p['total_amount'] or 0)
            p['percent'] = round(p['total'] / float(total_revenue) * 100, 1) if total_revenue > 0 else 0.0

        # Análise de Horários (00h a 23h)
        hours_agg = list(
            valid_orders.annotate(hour=ExtractHour('created_at'))
            .values('hour')
            .annotate(
                count=Count('id'),
                revenue=Sum('total'),
                online_count=Count('id', filter=Q(origin=Order.ORIGIN_ONLINE)),
                pdv_count=Count('id', filter=Q(origin=Order.ORIGIN_PDV))
            )
            .order_by('hour')
        )

        hours_dict = {h['hour']: h for h in hours_agg}
        hourly_distribution = []
        for h in range(24):
            data = hours_dict.get(h, {
                'hour': h,
                'count': 0,
                'revenue': Decimal('0.00'),
                'online_count': 0,
                'pdv_count': 0
            })
            hourly_distribution.append({
                'hour': f"{h:02d}h",
                'count': data['count'],
                'revenue': float(data['revenue'] or 0),
                'online_count': data['online_count'],
                'pdv_count': data['pdv_count']
            })

        # Identifica horários de pico
        sorted_by_revenue = sorted(hourly_distribution, key=lambda x: x['revenue'], reverse=True)
        peak_hours = [item['hour'] for item in sorted_by_revenue[:3] if item['revenue'] > 0]

        # Cancelamentos
        cancelled_qs = orders_qs.filter(status=Order.STATUS_CANCELLED)
        cancelled_total = cancelled_qs.count()
        cancelled_online = cancelled_qs.filter(origin=Order.ORIGIN_ONLINE).count()
        cancelled_pdv = cancelled_qs.filter(origin=Order.ORIGIN_PDV).count()
        total_all = orders_qs.count()
        cancel_rate = (cancelled_total / total_all * 100) if total_all > 0 else 0.0

        return {
            'total_revenue': total_revenue,
            'total_subtotal': total_subtotal,
            'total_delivery': total_delivery,
            'total_discounts': total_discounts,
            'payment_stats': payment_stats,
            'hourly_distribution': hourly_distribution,
            'peak_hours': peak_hours,
            'cancelled_total': cancelled_total,
            'cancelled_online': cancelled_online,
            'cancelled_pdv': cancelled_pdv,
            'cancel_rate': round(cancel_rate, 1),
        }

    # =========================================================================
    # 4. PRODUTOS
    # =========================================================================
    def get_product_metrics(self) -> Dict[str, Any]:
        order_items = OrderItem.objects.filter(
            order__store=self.store,
            order__created_at__range=(self.start_dt, self.end_dt)
        ).exclude(order__status=Order.STATUS_CANCELLED)

        # Agregação por produto
        products_sales = list(
            order_items.values('product_id', 'product_name')
            .annotate(
                qty=Sum('quantity'),
                total_revenue=Sum('total'),
                orders_count=Count('order_id', distinct=True),
                last_sold_at=Max('order__created_at')
            )
            .order_by('-qty')
        )

        all_sold_product_ids = {p['product_id'] for p in products_sales if p['product_id']}

        for p in products_sales:
            qty = p['qty'] or 0
            rev = p['total_revenue'] or Decimal('0.00')
            p['ticket_medio'] = (rev / qty) if qty > 0 else Decimal('0.00')

        top_selling = products_sales[:15]
        low_volume = sorted(products_sales, key=lambda x: x['qty'])[:15]

        # Produtos ativos sem nenhuma venda no período
        unsold_products = list(
            Product.objects.filter(store=self.store, is_active=True)
            .exclude(id__in=all_sold_product_ids)
            .select_related('category')
            .values('id', 'name', 'category__name', 'price', 'stock_quantity', 'track_stock')
        )

        # Última venda histórica de produtos sem venda no período
        for u in unsold_products:
            last_order = OrderItem.objects.filter(
                product_id=u['id']
            ).exclude(order__status=Order.STATUS_CANCELLED).order_by('-created_at').first()
            u['last_sold'] = last_order.created_at if last_order else None

        return {
            'top_selling': top_selling,
            'low_volume': low_volume,
            'unsold_products': unsold_products[:25],
            'unsold_count': len(unsold_products),
            'total_items_sold': order_items.aggregate(s=Sum('quantity'))['s'] or 0,
        }

    # =========================================================================
    # 5. OPERAÇÃO & ATRASOS
    # =========================================================================
    def get_operations_metrics(self) -> Dict[str, Any]:
        orders_qs = Order.objects.filter(
            store=self.store,
            created_at__range=(self.start_dt, self.end_dt)
        ).exclude(status=Order.STATUS_CANCELLED)

        standard_prep_min = self.store.preparation_time_minutes or 30

        # Filtra apenas pedidos que possuem timestamps reais registrados
        orders_with_timestamps = list(
            orders_qs.filter(accepted_at__isnull=False)
            .only('id', 'order_number', 'created_at', 'accepted_at', 'preparing_at', 'ready_at', 'status')
        )

        accept_durations = []
        prep_durations = []
        total_durations = []
        delayed_orders = []

        now = timezone.localtime()

        for o in orders_with_timestamps:
            # 1. Tempo até aceite
            if o.accepted_at and o.created_at:
                diff_sec = (o.accepted_at - o.created_at).total_seconds()
                if diff_sec >= 0:
                    accept_durations.append(diff_sec / 60.0)

            # 2. Tempo de preparo
            if o.ready_at and o.accepted_at:
                diff_prep = (o.ready_at - o.accepted_at).total_seconds()
                if diff_prep >= 0:
                    prep_min = diff_prep / 60.0
                    prep_durations.append(prep_min)
                    if prep_min > standard_prep_min:
                        delayed_orders.append({
                            'order_number': o.order_number,
                            'delay_minutes': round(prep_min - standard_prep_min, 1),
                            'prep_minutes': round(prep_min, 1),
                            'time': o.accepted_at
                        })
            elif o.status in [Order.STATUS_ACCEPTED, Order.STATUS_PREPARING] and o.accepted_at:
                # Pedido em andamento que já estourou o prazo
                elapsed_min = (now - o.accepted_at).total_seconds() / 60.0
                if elapsed_min > standard_prep_min:
                    delayed_orders.append({
                        'order_number': o.order_number,
                        'delay_minutes': round(elapsed_min - standard_prep_min, 1),
                        'prep_minutes': round(elapsed_min, 1),
                        'time': o.accepted_at
                    })

            # 3. Tempo total de produção
            if o.ready_at and o.created_at:
                diff_tot = (o.ready_at - o.created_at).total_seconds()
                if diff_tot >= 0:
                    total_durations.append(diff_tot / 60.0)

        has_operational_data = len(accept_durations) > 0 or len(prep_durations) > 0

        avg_accept_min = (sum(accept_durations) / len(accept_durations)) if accept_durations else None
        avg_prep_min = (sum(prep_durations) / len(prep_durations)) if prep_durations else None
        avg_total_min = (sum(total_durations) / len(total_durations)) if total_durations else None

        delayed_count = len(delayed_orders)
        total_eval = len(prep_durations)
        delayed_pct = (delayed_count / total_eval * 100) if total_eval > 0 else 0.0

        delays = [d['delay_minutes'] for d in delayed_orders]
        avg_delay_min = (sum(delays) / len(delays)) if delays else 0.0
        max_delay_min = max(delays) if delays else 0.0

        # Produtos com maior tempo médio de preparo
        # Analisa pedidos concluídos com ready_at
        orders_ready_ids = [o.id for o in orders_with_timestamps if o.ready_at and o.accepted_at]
        prep_time_by_order = {
            o.id: (o.ready_at - o.accepted_at).total_seconds() / 60.0
            for o in orders_with_timestamps if o.ready_at and o.accepted_at
        }

        product_prep_map = {}
        if orders_ready_ids:
            items = OrderItem.objects.filter(order_id__in=orders_ready_ids).values('product_name', 'order_id')
            for it in items:
                name = it['product_name']
                dur = prep_time_by_order.get(it['order_id'])
                if dur is not None:
                    product_prep_map.setdefault(name, []).append(dur)

        products_prep_ranking = []
        for name, durations in product_prep_map.items():
            if len(durations) >= 1:
                products_prep_ranking.append({
                    'product_name': name,
                    'orders_count': len(durations),
                    'avg_prep_min': round(sum(durations) / len(durations), 1)
                })

        products_prep_ranking.sort(key=lambda x: x['avg_prep_min'], reverse=True)

        return {
            'has_operational_data': has_operational_data,
            'standard_prep_min': standard_prep_min,
            'avg_accept_min': round(avg_accept_min, 1) if avg_accept_min is not None else None,
            'avg_prep_min': round(avg_prep_min, 1) if avg_prep_min is not None else None,
            'avg_total_min': round(avg_total_min, 1) if avg_total_min is not None else None,
            'delayed_count': delayed_count,
            'delayed_pct': round(delayed_pct, 1),
            'avg_delay_min': round(avg_delay_min, 1),
            'max_delay_min': round(max_delay_min, 1),
            'delayed_orders': delayed_orders[:10],
            'products_prep_ranking': products_prep_ranking[:10],
        }

    # =========================================================================
    # 6. PDV (BALCÃO)
    # =========================================================================
    def get_pos_metrics(self) -> Dict[str, Any]:
        pos_orders = Order.objects.filter(
            store=self.store,
            origin=Order.ORIGIN_PDV,
            created_at__range=(self.start_dt, self.end_dt)
        )
        valid_pos = pos_orders.exclude(status=Order.STATUS_CANCELLED)
        total_orders = valid_pos.count()
        total_revenue = valid_pos.aggregate(rev=Sum('total'))['rev'] or Decimal('0.00')
        ticket_medio = (total_revenue / total_orders) if total_orders > 0 else Decimal('0.00')

        # Formas de pagamento no PDV
        payment_labels = dict(Order.PAYMENT_CHOICES)
        payment_stats = list(
            valid_pos.values('payment_method')
            .annotate(count=Count('id'), total_amount=Sum('total'))
            .order_by('-total_amount')
        )
        for p in payment_stats:
            p['label'] = payment_labels.get(p['payment_method'], p['payment_method'])
            p['total'] = float(p['total_amount'] or 0)
            p['percent'] = round(p['total'] / float(total_revenue) * 100, 1) if total_revenue > 0 else 0.0

        # Produtos mais vendidos no balcão
        pos_items = OrderItem.objects.filter(
            order__store=self.store,
            order__origin=Order.ORIGIN_PDV,
            order__created_at__range=(self.start_dt, self.end_dt)
        ).exclude(order__status=Order.STATUS_CANCELLED)

        top_pos_products = list(
            pos_items.values('product_name')
            .annotate(qty=Sum('quantity'), total_amount=Sum('total'))
            .order_by('-qty')[:10]
        )
        for it in top_pos_products:
            it['total'] = it.get('total_amount') or Decimal('0.00')

        # Horários de maior movimento no PDV
        pos_hours = list(
            valid_pos.annotate(hour=ExtractHour('created_at'))
            .values('hour')
            .annotate(count=Count('id'), revenue=Sum('total'))
            .order_by('-count')[:5]
        )
        peak_hours = [f"{h['hour']:02d}h ({h['count']} vendas)" for h in pos_hours]

        return {
            'total_orders': total_orders,
            'total_revenue': total_revenue,
            'ticket_medio': ticket_medio,
            'payment_stats': payment_stats,
            'top_pos_products': top_pos_products,
            'peak_hours': peak_hours,
        }

    # =========================================================================
    # 7. ESTOQUE
    # =========================================================================
    def get_stock_metrics(self) -> Dict[str, Any]:
        tracked_products = Product.objects.filter(store=self.store, track_stock=True, is_active=True)

        out_of_stock = list(
            tracked_products.filter(stock_quantity__lte=0)
            .select_related('category')
            .values('id', 'name', 'category__name', 'stock_quantity')
        )

        critical_stock = list(
            tracked_products.filter(stock_quantity__gt=0, stock_quantity__lte=5)
            .select_related('category')
            .values('id', 'name', 'category__name', 'stock_quantity')
        )

        # Movimentações no período
        movements = StockMovement.objects.filter(
            store=self.store,
            created_at__range=(self.start_dt, self.end_dt)
        )

        sales_online_qty = abs(movements.filter(movement_type=StockMovement.TYPE_SALE_ONLINE).aggregate(s=Sum('quantity'))['s'] or 0)
        sales_pdv_qty = abs(movements.filter(movement_type=StockMovement.TYPE_SALE_PDV).aggregate(s=Sum('quantity'))['s'] or 0)
        cancel_return_qty = abs(movements.filter(movement_type=StockMovement.TYPE_CANCEL_RETURN).aggregate(s=Sum('quantity'))['s'] or 0)
        restock_qty = abs(movements.filter(movement_type=StockMovement.TYPE_RESTOCK).aggregate(s=Sum('quantity'))['s'] or 0)

        # Produtos mais consumidos
        most_consumed = list(
            movements.filter(movement_type__in=[StockMovement.TYPE_SALE_ONLINE, StockMovement.TYPE_SALE_PDV])
            .values('product__name')
            .annotate(consumed=Sum('quantity'))
            .order_by('consumed')[:10]  # Saídas são negativas
        )
        for m in most_consumed:
            m['consumed'] = abs(m['consumed'] or 0)

        # Produtos sem movimentação de saída
        active_ids = set(tracked_products.values_list('id', flat=True))
        moved_ids = set(
            movements.filter(movement_type__in=[StockMovement.TYPE_SALE_ONLINE, StockMovement.TYPE_SALE_PDV])
            .values_list('product_id', flat=True)
        )
        idle_stock_ids = active_ids - moved_ids
        idle_products = list(
            Product.objects.filter(id__in=idle_stock_ids)
            .select_related('category')
            .values('id', 'name', 'category__name', 'stock_quantity')[:15]
        )

        return {
            'out_of_stock': out_of_stock,
            'critical_stock': critical_stock,
            'out_of_stock_count': len(out_of_stock),
            'critical_stock_count': len(critical_stock),
            'sales_online_qty': sales_online_qty,
            'sales_pdv_qty': sales_pdv_qty,
            'cancel_return_qty': cancel_return_qty,
            'restock_qty': restock_qty,
            'most_consumed': most_consumed,
            'idle_products': idle_products,
        }
