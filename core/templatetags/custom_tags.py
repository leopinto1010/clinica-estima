from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    # Tenta acessar como inteiro (se for dia da semana), senão acessa direto
    if isinstance(dictionary, dict):
        try:
            return dictionary.get(key)
        except (TypeError, AttributeError):
            return None
    return None

@register.filter
def dict_get(dictionary, key):
    if isinstance(dictionary, dict):
        try:
            return dictionary.get(int(key))
        except (ValueError, TypeError):
            return dictionary.get(key)
    return None