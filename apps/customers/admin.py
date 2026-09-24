from django.contrib import admin
from .models import Customer, CustomerAddress


class CustomerAddressInline(admin.StackedInline):
    model = CustomerAddress
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'store', 'document', 'orders_count', 'total_spent', 'created_at')
    list_filter = ('store',)
    search_fields = ('name', 'phone', 'document', 'store__name')
    ordering = ('-created_at',)
    inlines = [CustomerAddressInline]


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    list_display = ('customer', 'street', 'number', 'neighborhood', 'city', 'state', 'is_default')
    list_filter = ('state', 'is_default')
    search_fields = ('street', 'neighborhood', 'customer__name', 'customer__phone')
