from .decorators import is_admin, is_dono, is_terapeuta

def permissoes_globais(request):
    """
    Torna as verificações de permissão disponíveis em todos os templates.
    """
    if request.user.is_authenticated:
        return {
            'is_admin': is_admin(request.user),
            'is_dono': is_dono(request.user),
            'is_terapeuta': is_terapeuta(request.user),
        }
    return {}