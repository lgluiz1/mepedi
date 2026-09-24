from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    """
    Manager de usuário personalizado onde o email é o identificador único
    para autenticação no lugar de usernames tradicionais.
    """
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('O endereço de e-mail é obrigatório.'))
        email = self.normalize_email(email).lower()
        extra_fields.setdefault('is_active', True)
        # Se username não foi fornecido, usa a parte local do e-mail
        if not extra_fields.get('username'):
            extra_fields['username'] = email.split('@')[0]
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superusuário precisa ter is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superusuário precisa ter is_superuser=True.'))

        return self.create_user(email, password, **extra_fields)
