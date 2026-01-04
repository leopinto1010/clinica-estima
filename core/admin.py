from django.contrib import admin
from .models import Paciente, Terapeuta, Agendamento

# Aqui registramos as tabelas para aparecerem no painel
admin.site.register(Paciente)
admin.site.register(Terapeuta)
admin.site.register(Agendamento)