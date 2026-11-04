from django.contrib import admin

from .models import Assignment, Extension, Submission

admin.site.register(Assignment)
admin.site.register(Submission)
admin.site.register(Extension)
