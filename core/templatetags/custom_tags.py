from django import template

register = template.Library()

@register.filter
def dict_get(dictionary, key):
    """
    Permite acessar dicionário no template: dictionary|dict_get:key
    """
    if isinstance(dictionary, dict):
        # Tenta converter para inteiro, pois o loop do template envia string "0", "1"...
        try:
            return dictionary.get(int(key))
        except (ValueError, TypeError):
            return dictionary.get(key)
    return None