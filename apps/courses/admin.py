from django.contrib import admin

from .models import Category, Course, Enrolment, Group, Topic

admin.site.register(Category)
admin.site.register(Enrolment)
admin.site.register(Group)
admin.site.register(Topic)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "department", "semester", "is_visible")
    search_fields = ("code", "title")
