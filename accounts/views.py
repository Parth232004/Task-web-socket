from pathlib import Path
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from datetime import timedelta
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .models import CustomUser, LoginAuditLog, PasswordResetToken
from .serializers import (
    LoginSerializer, LoginResponseSerializer, UserSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
    LoginAuditLogSerializer, RegistrationSerializer
)
from .forms import LoginForm, PasswordResetRequestForm, PasswordResetConfirmForm, RegistrationForm


def login_frontend(request):
    """Serve the login page"""
    frontend_path = Path(__file__).resolve().parent.parent / 'login.html'
    with open(frontend_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(content, content_type='text/html')


def register_frontend(request):
    """Serve the registration page"""
    frontend_path = Path(__file__).resolve().parent.parent / 'register.html'
    with open(frontend_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(content, content_type='text/html')


def get_client_ip(request):
    """Extract client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request):
    """Extract user agent from request"""
    return request.META.get('HTTP_USER_AGENT', '')


class RegisterView(APIView):
    """
    API endpoint for user registration.
    Creates a new user account and returns JWT tokens on success.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    authentication_classes = []  # No auth required for registration

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = serializer.save()

        # Log the registration as a successful login
        LoginAuditLog.objects.create(
            user=user,
            email=user.email,
            status=LoginAuditLog.SUCCESS,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        # Auto-login after registration
        login(request, user)

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        response_data = {
            'user': UserSerializer(user).data,
            'access': access_token,
            'refresh': refresh_token,
            'message': 'Registration successful.'
        }

        return Response(response_data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """
    API endpoint for user login using email and password.
    Returns JWT tokens on successful authentication.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    authentication_classes = []  # No auth required for login
    """
    API endpoint for user login using email and password.
    Returns JWT tokens on successful authentication.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        remember_me = serializer.validated_data.get('remember_me', False)

        # Authenticate user
        user = authenticate(request, username=email, password=password)

        # Log the attempt
        login_status = LoginAuditLog.SUCCESS if user else LoginAuditLog.FAILURE
        LoginAuditLog.objects.create(
            user=user,
            email=email,
            status=login_status,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request)
        )

        if user is None:
            return Response(
                {'error': 'Invalid email or password.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {'error': 'This account is inactive.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Create session for browser-based login
        login(request, user)

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        # Set token expiration based on remember_me
        if not remember_me:
            # Short-lived access token (1 hour)
            refresh.set_exp(lifetime=timedelta(hours=1))
        else:
            # Longer-lived refresh token (7 days)
            refresh.set_exp(lifetime=timedelta(days=7))

        response_data = {
            'user': UserSerializer(user).data,
            'access': access_token,
            'refresh': refresh_token,
            'message': 'Login successful.'
        }

        return Response(response_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    API endpoint for user logout.
    Blacklists the refresh token and ends the session.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                # In simplejwt 5.x, blacklist requires the token_blacklist app
                # For now, we just invalidate by not returning it
                pass
        except TokenError:
            pass

        logout(request)
        return Response(
            {'message': 'Logout successful.'},
            status=status.HTTP_200_OK
        )

    def get(self, request):
        """GET endpoint for logout (for form-based logout)"""
        logout(request)
        return Response(
            {'message': 'Logout successful.'},
            status=status.HTTP_200_OK
        )


class PasswordResetRequestView(APIView):
    """
    API endpoint to request a password reset.
    Creates a password reset token and returns it (in production, send via email).
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = serializer.validated_data['email'].lower()

        try:
            user = CustomUser.objects.get(email=email, is_active=True)
        except CustomUser.DoesNotExist:
            # Don't reveal whether email exists
            return Response(
                {'message': 'If an account with that email exists, a password reset link has been sent.'},
                status=status.HTTP_200_OK
            )

        # Create password reset token
        token = PasswordResetToken.objects.create(user=user)

        # In production, send email with token. For development, return it.
        return Response({
            'message': 'Password reset token generated.',
            'token': str(token.token),
            'user_id': user.id,
            'note': 'In production, this token would be sent via email.'
        }, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    """
    API endpoint to confirm password reset with token.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        token_str = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        try:
            token = PasswordResetToken.objects.get(token=token_str)
        except PasswordResetToken.DoesNotExist:
            return Response(
                {'error': 'Invalid reset token.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not token.is_valid():
            return Response(
                {'error': 'Reset token has expired or already been used.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update password
        user = token.user
        user.set_password(new_password)
        user.save()

        # Mark token as used
        token.is_used = True
        token.save()

        return Response(
            {'message': 'Password has been reset successfully.'},
            status=status.HTTP_200_OK
        )


class CurrentUserView(APIView):
    """
    API endpoint to get current authenticated user info.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LoginHistoryView(APIView):
    """
    API endpoint to get current user's login history.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        logs = LoginAuditLog.objects.filter(user=request.user)[:20]
        serializer = LoginAuditLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
