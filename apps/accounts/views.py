from django.contrib.auth import authenticate, login, logout
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import RegisterMerchantSerializer, UserSerializer
from stores.serializers import StoreDetailSerializer


class RegisterMerchantView(APIView):
    """
    Endpoint de cadastro de novo lojista e sua primeira loja.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterMerchantSerializer(data=request.data)
        if serializer.is_valid():
            result = serializer.save()
            user = result['user']
            store = result['store']

            # Realiza login na sessão se for requisição web
            login(request, user)

            return Response({
                "message": "Lojista e loja cadastrados com sucesso!",
                "user": UserSerializer(user).data,
                "store": StoreDetailSerializer(store).data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    """
    Endpoint de login para lojistas.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {"error": "E-mail e senha são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=email, password=password)
        if not user:
            return Response(
                {"error": "Credenciais inválidas. Verifique seu e-mail e senha."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        login(request, user)
        # Obter lojas associadas ao usuário
        stores = [membership.store for membership in user.memberships.filter(is_active=True).select_related('store')]

        return Response({
            "message": "Login realizado com sucesso!",
            "user": UserSerializer(user).data,
            "stores": StoreDetailSerializer(stores, many=True).data
        })


class LogoutView(APIView):
    """
    Endpoint de logout.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"message": "Logout realizado com sucesso."})


class MeView(APIView):
    """
    Retorna os dados do usuário autenticado e suas lojas vinculadas.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        stores = [m.store for m in user.memberships.filter(is_active=True).select_related('store')]
        return Response({
            "user": UserSerializer(user).data,
            "stores": StoreDetailSerializer(stores, many=True).data
        })
