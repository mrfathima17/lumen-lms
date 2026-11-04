from django.contrib import admin

from .models import Event, TimetableSlot, TodoItem

admin.site.register(Event)
admin.site.register(TimetableSlot)
admin.site.register(TodoItem)
