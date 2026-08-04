from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from .models import Terapeuta

def is_admin(user):
    return user.is_authenticated and (
        user.is_superuser or 
        user.groups.filter(name__in=['Administrativo', 'Donos']).exists()
    )

def is_terapeuta(user):
    return user.is_authenticated and (
        user.is_superuser or
        user.groups.filter(name__in=['Terapeutas', 'Coordenação']).exists() or
        hasattr(user, 'terapeuta') and user.terapeuta is not None
    )

def is_dono(user):
    # Dono agora verifica o grupo 'Donos' também
    return user.is_authenticated and (
        user.is_superuser or 
        user.groups.filter(name='Donos').exists()
    )

def is_coordenadora(user):
    if not user.is_authenticated:
        return False
    if user.groups.filter(name='Coordenação').exists():
        return True
    try:
        terapeuta = user.terapeuta
    except Terapeuta.DoesNotExist:
        return False
    return bool(terapeuta and terapeuta.coordenacao)

# --- Decorators para usar nas Views ---

def admin_required(function=None):
    actual_decorator = user_passes_test(
        is_admin,
        login_url='login',
        redirect_field_name=None
    )
    if function:
        return actual_decorator(function)
    return actual_decorator

def terapeuta_required(function=None):
    actual_decorator = user_passes_test(
        is_terapeuta,
        login_url='login',
        redirect_field_name=None
    )
    if function:
        return actual_decorator(function)
    return actual_decorator

def dono_required(function=None):
    actual_decorator = user_passes_test(
        is_dono,
        login_url='login',
        redirect_field_name=None
    )
    if function:
        return actual_decorator(function)
    return actual_decorator