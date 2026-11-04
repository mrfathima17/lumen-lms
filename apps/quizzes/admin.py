from django.contrib import admin

from .models import Answer, Attempt, Choice, Question, Quiz

for m in (Quiz, Question, Choice, Attempt, Answer):
    admin.site.register(m)
