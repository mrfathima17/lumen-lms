from django.contrib import admin

from .models import CourseResult, GradeBand, GradeItem, ManualMark

admin.site.register(GradeBand)
admin.site.register(GradeItem)
admin.site.register(ManualMark)
admin.site.register(CourseResult)
