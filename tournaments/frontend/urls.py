from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from . import views


urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('t/create', views.CreateTournamentView.as_view(), name='create-tournament'),
    path('t/update/<int:pk>', views.UpdateTournamentView.as_view(), name='update-tournament'),
    path('t/publish/<int:pk>', views.PublishTournamentView.as_view(), name='publish-tournament'),
    path('t/draft/<int:pk>', views.DraftTournamentView.as_view(), name='draft-tournament'),
    path('t/delete/<int:pk>', views.DeleteTournamentView.as_view(), name='delete-tournament'),
    path('t/join/<int:pk>', views.JoinTournamentView.as_view(), name='join-tournament'),
    path('t/withdraw/<int:pk>', views.WithdrawTournamentView.as_view(), name='withdraw-tournament'),
    path('t/active/<int:pk>', views.ActiveTournamentView.as_view(), name='active-tournament'),
    path('accounts/login/', LoginView.as_view(template_name = 'frontend/login.html'), name='login'),
    path('accounts/signup/', views.SignupView.as_view(), name='signup'),
    path('accounts/logout/', LogoutView.as_view(), name='logout'),
]
