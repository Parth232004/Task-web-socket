from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='api_register'),
    path('register/page/', views.register_frontend, name='register_page'),
    path('login/', views.LoginView.as_view(), name='api_login'),
    path('login/page/', views.login_frontend, name='login_page'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('me/', views.CurrentUserView.as_view(), name='current_user'),
    path('login-history/', views.LoginHistoryView.as_view(), name='login_history'),
]
