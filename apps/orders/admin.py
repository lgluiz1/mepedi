from django.contrib import admin
from .models import Order, OrderItem, OrderItemOption, Coupon, Table, TableSession


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'store', 'is_active', 'qr_token')
    list_filter = ('store', 'is_active')
    search_fields = ('number', 'name', 'store__name')
    readonly_fields = ('qr_token',)


@admin.register(TableSession)
class TableSessionAdmin(admin.ModelAdmin):
    list_display = ('table', 'store', 'status', 'opened_at', 'closed_at', 'total_paid')
    list_filter = ('store', 'status', 'opened_at')
    search_fields = ('table__number', 'store__name')
    readonly_fields = ('session_token', 'opened_at')


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'store', 'discount_type', 'discount_value', 'times_used', 'is_active')
    list_filter = ('store', 'is_active', 'discount_type')
    search_fields = ('code', 'store__name')



class OrderItemOptionInline(admin.TabularInline):
    model = OrderItemOption
    extra = 0
    readonly_fields = ('name', 'price', 'group_name')
    can_delete = False


class OrderItemInline(admin.StackedInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_name', 'unit_price', 'quantity', 'subtotal', 'total', 'notes')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'display_number', 'store', 'customer', 'delivery_type',
        'payment_method', 'subtotal', 'delivery_fee', 'total', 'status', 'created_at'
    )
    list_filter = ('store', 'status', 'delivery_type', 'payment_method', 'created_at')
    search_fields = ('order_number', 'customer__name', 'customer__phone', 'store__name')
    readonly_fields = ('public_id', 'order_number', 'subtotal', 'delivery_fee', 'total', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    inlines = [OrderItemInline]

    actions = ['mark_as_accepted', 'mark_as_preparing', 'mark_as_ready', 'mark_as_completed']

    @admin.action(description="Marcar pedidos selecionados como ACEITO")
    def mark_as_accepted(self, request, queryset):
        queryset.update(status=Order.STATUS_ACCEPTED)

    @admin.action(description="Marcar pedidos selecionados como EM PREPARAÇÃO")
    def mark_as_preparing(self, request, queryset):
        queryset.update(status=Order.STATUS_PREPARING)

    @admin.action(description="Marcar pedidos selecionados como PRONTO")
    def mark_as_ready(self, request, queryset):
        queryset.update(status=Order.STATUS_READY)

    @admin.action(description="Marcar pedidos selecionados como CONCLUÍDO")
    def mark_as_completed(self, request, queryset):
        queryset.update(status=Order.STATUS_COMPLETED)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product_name', 'unit_price', 'quantity', 'total')
    list_filter = ('order__store',)
    search_fields = ('product_name', 'order__customer__name')
    inlines = [OrderItemOptionInline]
