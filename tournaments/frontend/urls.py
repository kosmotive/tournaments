from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from . import views


urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('tournaments/create', views.CreateTournamentView.as_view(), name='tournaments/create'),
    path('accounts/login/', LoginView.as_view(template_name = 'frontend/login.html'), name='login'),
    path('accounts/logout/', LogoutView.as_view(), name='logout'),
]
