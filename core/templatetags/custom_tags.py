from django import template

register = template.Library()

@register.filter
def dict_get(dictionary, key):
    """
    Permite acessar dicionário no template: dictionary|dict_get:key
    Tenta acessar com chave inteira primeiro (útil para loops numéricos),
    depois com chave string.
    """
    if isinstance(dictionary, dict):
        try:
            return dictionary.get(int(key))
        except (ValueError, TypeError):
            return dictionary.get(key)
    return None

# Adiciona 'get_item' como um alias (apelido) para a mesma função 'dict_get'
# Isso corrige o erro no lista_agendamentos.html sem quebrar o lista_agendas_fixas.html
register.filter('get_item', dict_get)