from django.contrib import admin
from .models import Store, BusinessHour


class BusinessHourInline(admin.TabularInline):
    model = BusinessHour
    extra = 7
    max_num = 7


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'owner', 'phone', 'whatsapp', 'is_open', 'is_paused', 'is_active', 'created_at')
    list_filter = ('is_active', 'is_open', 'is_paused', 'state')
    search_fields = ('name', 'slug', 'owner__email', 'whatsapp', 'document')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [BusinessHourInline]


@admin.register(BusinessHour)
class BusinessHourAdmin(admin.ModelAdmin):
    list_display = ('store', 'weekday', 'opening_time', 'closing_time', 'is_closed')
    list_filter = ('weekday', 'is_closed')
    search_fields = ('store__name',)
