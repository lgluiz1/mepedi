from django.urls import path
from . import admin_views

app_name = 'saas_admin'

urlpatterns = [
    path('', admin_views.saas_admin_dashboard_view, name='dashboard'),
    path('lojistas/', admin_views.saas_admin_merchants_view, name='merchants'),
    path('lojas/<int:store_id>/', admin_views.saas_admin_store_detail_view, name='store_detail'),
    path('lojas/<int:store_id>/mudar-plano/', admin_views.saas_admin_change_plan_view, name='change_plan'),
    path('lojas/<int:store_id>/estender-trial/', admin_views.saas_admin_extend_trial_view, name='extend_trial'),
    path('lojas/<int:store_id>/status/', admin_views.saas_admin_toggle_store_status_view, name='toggle_status'),
    path('lojas/<int:store_id>/suporte/', admin_views.saas_admin_support_start_view, name='support_start'),
    path('suporte/sair/', admin_views.saas_admin_support_end_view, name='support_end'),
    path('financeiro/', admin_views.saas_admin_finance_view, name='finance'),
    path('gateways/', admin_views.saas_admin_gateways_view, name='gateways'),
    path('gateways/testar/', admin_views.saas_admin_test_gateway_view, name='test_gateway'),
    path('auditoria/', admin_views.saas_admin_audit_view, name='audit'),
]
