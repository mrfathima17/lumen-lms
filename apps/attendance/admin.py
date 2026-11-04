from django.contrib import admin

from .models import AttendanceRecord, AttendanceSession

admin.site.register(AttendanceSession)
admin.site.register(AttendanceRecord)
