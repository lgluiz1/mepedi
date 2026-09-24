from django.http import JsonResponse
from django.shortcuts import render


def health_check(request):
    """
    Endpoint simples de verificação de integridade da API e status do sistema.
    """
    return JsonResponse({
        "status": "healthy",
        "service": "IA-Pedidos API",
        "version": "1.0.0"
    })


def platform_home(request):
    """
    Página inicial da plataforma SaaS IA-Pedidos.
    """
    return render(request, 'core/home.html')
