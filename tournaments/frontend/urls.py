from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from . import views


urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('tournaments/create', views.CreateTournamentView.as_view(), name='create-tournament'),
    path('tournaments/update/<int:pk>', views.UpdateTournamentView.as_view(), name='update-tournament'),
    path('tournaments/publish/<int:pk>', views.PublishTournamentView.as_view(), name='publish-tournament'),
    path('accounts/login/', LoginView.as_view(template_name = 'frontend/login.html'), name='login'),
    path('accounts/logout/', LogoutView.as_view(), name='logout'),
]
