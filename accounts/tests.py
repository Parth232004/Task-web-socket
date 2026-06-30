"""
Comprehensive test suite for the accounts app.
Covers unit tests for models and integration tests for authentication API endpoints.
"""
from typing import List, Dict
from datetime import date, time, timedelta
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from .models import CustomUser, LoginAuditLog, PasswordResetToken
from .forms import LoginForm, PasswordResetRequestForm, PasswordResetConfirmForm
from .serializers import (
    UserSerializer, LoginSerializer, PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer, LoginAuditLogSerializer
)

User = get_user_model()


class CustomUserModelTestCase(TestCase):
    """Unit tests for CustomUser model"""

    def setUp(self):
        self.user_data = {
            'email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'testpass123'
        }

    def test_create_user(self):
        """Test creating a regular user"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.first_name, 'Test')
        self.assertEqual(user.last_name, 'User')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('testpass123'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser(self):
        """Test creating a superuser"""
        admin = User.objects.create_superuser(
            email='admin@example.com',
            password='adminpass123'
        )
        self.assertEqual(admin.email, 'admin@example.com')
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_email_is_username_field(self):
        """Test that email is used as the username field"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.username, None)
        self.assertEqual(user.get_username(), user.email)

    def test_email_unique_constraint(self):
        """Test that email must be unique"""
        User.objects.create_user(**self.user_data)
        with self.assertRaises(Exception):
            User.objects.create_user(**self.user_data)

    def test_get_full_name(self):
        """Test get_full_name method"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.get_full_name(), 'Test User')

    def test_get_full_name_empty(self):
        """Test get_full_name with empty names returns email"""
        user = User.objects.create_user(
            email='empty@example.com',
            password='testpass123'
        )
        self.assertEqual(user.get_full_name(), 'empty@example.com')

    def test_get_short_name(self):
        """Test get_short_name method"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.get_short_name(), 'Test')

    def test_str_representation(self):
        """Test string representation"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(str(user), 'test@example.com')


class LoginAuditLogModelTestCase(TestCase):
    """Unit tests for LoginAuditLog model"""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )

    def test_create_login_audit_log(self):
        """Test creating a login audit log entry"""
        log = LoginAuditLog.objects.create(
            user=self.user,
            email=self.user.email,
            status=LoginAuditLog.SUCCESS,
            ip_address='192.168.1.1',
            user_agent='Mozilla/5.0'
        )
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.status, LoginAuditLog.SUCCESS)
        self.assertEqual(log.ip_address, '192.168.1.1')

    def test_create_failed_login_log(self):
        """Test creating a failed login audit log"""
        log = LoginAuditLog.objects.create(
            user=None,
            email='nonexistent@example.com',
            status=LoginAuditLog.FAILURE,
            ip_address='10.0.0.1'
        )
        self.assertIsNone(log.user)
        self.assertEqual(log.status, LoginAuditLog.FAILURE)

    def test_str_representation(self):
        """Test string representation"""
        log = LoginAuditLog.objects.create(
            user=self.user,
            email=self.user.email,
            status=LoginAuditLog.SUCCESS
        )
        expected = f'{self.user.email} - success at {log.timestamp}'
        self.assertEqual(str(log), expected)

    def test_ordering(self):
        """Test that logs are ordered by timestamp descending"""
        log1 = LoginAuditLog.objects.create(
            user=self.user, email=self.user.email, status=LoginAuditLog.SUCCESS
        )
        log2 = LoginAuditLog.objects.create(
            user=self.user, email=self.user.email, status=LoginAuditLog.FAILURE
        )
        logs = LoginAuditLog.objects.all()
        self.assertEqual(logs[0], log2)  # Most recent first
        self.assertEqual(logs[1], log1)


class PasswordResetTokenModelTestCase(TestCase):
    """Unit tests for PasswordResetToken model"""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )

    def test_create_token(self):
        """Test creating a password reset token"""
        token = PasswordResetToken.objects.create(user=self.user)
        self.assertEqual(token.user, self.user)
        self.assertFalse(token.is_used)
        self.assertTrue(token.is_valid())

    def test_token_expiration(self):
        """Test token expiration logic"""
        token = PasswordResetToken.objects.create(user=self.user)
        # Token should be valid immediately
        self.assertTrue(token.is_valid())

        # Simulate expired token
        from django.utils import timezone as tz
        token.expires_at = tz.now() - timedelta(hours=1)
        token.save()
        self.assertFalse(token.is_valid())

    def test_used_token_invalid(self):
        """Test that used tokens are invalid"""
        token = PasswordResetToken.objects.create(user=self.user)
        token.is_used = True
        token.save()
        self.assertFalse(token.is_valid())

    def test_str_representation(self):
        """Test string representation"""
        token = PasswordResetToken.objects.create(user=self.user)
        expected = f'Password reset token for {self.user.email}'
        self.assertEqual(str(token), expected)


class LoginFormTestCase(TestCase):
    """Unit tests for login form"""

    def test_valid_form(self):
        """Test form with valid data"""
        user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        form_data = {
            'email': 'test@example.com',
            'password': 'testpass123',
            'remember_me': True
        }
        form = LoginForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['user'], user)

    def test_invalid_email(self):
        """Test form with invalid email"""
        form_data = {
            'email': 'invalid-email',
            'password': 'testpass123'
        }
        form = LoginForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_wrong_password(self):
        """Test form with wrong password"""
        User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        form_data = {
            'email': 'test@example.com',
            'password': 'wrongpass'
        }
        form = LoginForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_missing_fields(self):
        """Test form with missing fields"""
        form = LoginForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertIn('password', form.errors)


class PasswordResetFormTestCase(TestCase):
    """Unit tests for password reset forms"""

    def test_valid_request_form(self):
        """Test password reset request form"""
        form_data = {'email': 'test@example.com'}
        form = PasswordResetRequestForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_invalid_email_request_form(self):
        """Test password reset request form with invalid email"""
        form_data = {'email': 'invalid'}
        form = PasswordResetRequestForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_valid_confirm_form(self):
        """Test password reset confirm form"""
        import uuid
        form_data = {
            'token': str(uuid.uuid4()),
            'new_password': 'newpass123',
            'confirm_password': 'newpass123'
        }
        form = PasswordResetConfirmForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_password_mismatch(self):
        """Test password reset confirm form with mismatched passwords"""
        import uuid
        form_data = {
            'token': str(uuid.uuid4()),
            'new_password': 'newpass123',
            'confirm_password': 'different123'
        }
        form = PasswordResetConfirmForm(data=form_data)
        self.assertFalse(form.is_valid())


class LoginAPITestCase(APITestCase):
    """Integration tests for login API"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )

    def test_login_success(self):
        """Test successful login"""
        response = self.client.post(
            '/api/login/',
            {'email': 'test@example.com', 'password': 'testpass123'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)  # type: ignore[attr-defined]
        self.assertIn('refresh', response.data)  # type: ignore[attr-defined]
        self.assertIn('user', response.data)  # type: ignore[attr-defined]
        self.assertEqual(response.data['user']['email'], 'test@example.com')  # type: ignore[attr-defined]

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = self.client.post(
            '/api/login/',
            {'email': 'test@example.com', 'password': 'wrongpass'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_missing_email(self):
        """Test login with missing email"""
        response = self.client.post(
            '/api/login/',
            {'password': 'testpass123'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_missing_password(self):
        """Test login with missing password"""
        response = self.client.post(
            '/api/login/',
            {'email': 'test@example.com'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_nonexistent_user(self):
        """Test login with non-existent user"""
        response = self.client.post(
            '/api/login/',
            {'email': 'nonexistent@example.com', 'password': 'testpass123'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_creates_audit_log(self):
        """Test that login creates an audit log entry"""
        initial_count = LoginAuditLog.objects.count()
        self.client.post(
            '/api/login/',
            {'email': 'test@example.com', 'password': 'testpass123'},
            format='json'
        )
        self.assertEqual(LoginAuditLog.objects.count(), initial_count + 1)
        log = LoginAuditLog.objects.first()
        self.assertEqual(log.email, 'test@example.com')
        self.assertEqual(log.status, LoginAuditLog.SUCCESS)


class LogoutAPITestCase(APITestCase):
    """Integration tests for logout API"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )

    def test_logout_success(self):
        """Test successful logout"""
        # First login to get tokens
        login_response = self.client.post(
            '/api/login/',
            {'email': 'test@example.com', 'password': 'testpass123'},
            format='json'
        )
        access_token = login_response.data['access']  # type: ignore[attr-defined]
        refresh_token = login_response.data['refresh']  # type: ignore[attr-defined]

        # Authenticate
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')

        # Logout
        response = self.client.post(
            '/api/logout/',
            {'refresh': refresh_token},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_without_auth(self):
        """Test logout without authentication"""
        response = self.client.post('/api/logout/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PasswordResetAPITestCase(APITestCase):
    """Integration tests for password reset API"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )

    def test_request_reset_success(self):
        """Test successful password reset request"""
        response = self.client.post(
            '/api/password-reset/',
            {'email': 'test@example.com'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)  # type: ignore[attr-defined]

    def test_request_reset_nonexistent_email(self):
        """Test password reset request with non-existent email"""
        response = self.client.post(
            '/api/password-reset/',
            {'email': 'nonexistent@example.com'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should not reveal if email exists

    def test_confirm_reset_success(self):
        """Test successful password reset confirmation"""
        # Create token
        token = PasswordResetToken.objects.create(user=self.user)

        response = self.client.post(
            '/api/password-reset/confirm/',
            {
                'token': str(token.token),
                'new_password': 'newpass123',
                'confirm_password': 'newpass123'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify password changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpass123'))

    def test_confirm_reset_invalid_token(self):
        """Test password reset with invalid token"""
        response = self.client.post(
            '/api/password-reset/confirm/',
            {
                'token': '00000000-0000-0000-0000-000000000000',
                'new_password': 'newpass123',
                'confirm_password': 'newpass123'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_reset_password_mismatch(self):
        """Test password reset with mismatched passwords"""
        token = PasswordResetToken.objects.create(user=self.user)
        response = self.client.post(
            '/api/password-reset/confirm/',
            {
                'token': str(token.token),
                'new_password': 'newpass123',
                'confirm_password': 'different123'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CurrentUserAPITestCase(APITestCase):
    """Integration tests for current user API"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )

    def test_get_current_user(self):
        """Test getting current user info"""
        # Login
        login_response = self.client.post(
            '/api/login/',
            {'email': 'test@example.com', 'password': 'testpass123'},
            format='json'
        )
        access_token = login_response.data['access']  # type: ignore[attr-defined]
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')

        # Get current user
        response = self.client.get('/api/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'test@example.com')  # type: ignore[attr-defined]
        self.assertEqual(response.data['first_name'], 'Test')  # type: ignore[attr-defined]
        self.assertEqual(response.data['last_name'], 'User')  # type: ignore[attr-defined]

    def test_get_current_user_unauthenticated(self):
        """Test getting current user without auth"""
        response = self.client.get('/api/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LoginHistoryAPITestCase(APITestCase):
    """Integration tests for login history API"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )

    def test_get_login_history(self):
        """Test getting login history"""
        # Create some login logs
        LoginAuditLog.objects.create(
            user=self.user,
            email=self.user.email,
            status=LoginAuditLog.SUCCESS,
            ip_address='192.168.1.1'
        )
        LoginAuditLog.objects.create(
            user=self.user,
            email=self.user.email,
            status=LoginAuditLog.FAILURE,
            ip_address='10.0.0.1'
        )

        # Login
        login_response = self.client.post(
            '/api/login/',
            {'email': 'test@example.com', 'password': 'testpass123'},
            format='json'
        )
        access_token = login_response.data['access']  # type: ignore[attr-defined]
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')

        # Get history
        response = self.client.get('/api/login-history/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)  # 2 created + 1 from login  # type: ignore[attr-defined]

    def test_get_login_history_unauthenticated(self):
        """Test getting login history without auth"""
        response = self.client.get('/api/login-history/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LoginPageTestCase(TestCase):
    """Tests for login page rendering"""

    def test_login_page_loads(self):
        """Test that login page loads successfully"""
        response = self.client.get('/api/login/page/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome Back')
        self.assertContains(response, 'Sign in to your account')
        self.assertContains(response, 'email')
        self.assertContains(response, 'password')
        self.assertContains(response, 'Remember me')
        self.assertContains(response, 'Forgot password')


class RegistrationAPITestCase(APITestCase):
    """Integration tests for registration API"""

    def setUp(self):
        self.client = APIClient()
        self.valid_data = {
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password': 'newpass123',
            'confirm_password': 'newpass123'
        }

    def test_registration_success(self):
        """Test successful user registration"""
        response = self.client.post(
            '/api/register/',
            self.valid_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)  # type: ignore[attr-defined]
        self.assertIn('refresh', response.data)  # type: ignore[attr-defined]
        self.assertIn('user', response.data)  # type: ignore[attr-defined]
        self.assertEqual(response.data['user']['email'], 'newuser@example.com')  # type: ignore[attr-defined]

        # Verify user was created in database
        self.assertTrue(User.objects.filter(email='newuser@example.com').exists())
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.first_name, 'New')
        self.assertEqual(user.last_name, 'User')

    def test_registration_duplicate_email(self):
        """Test registration with existing email fails"""
        User.objects.create_user(
            email='existing@example.com',
            password='testpass123'
        )
        data = self.valid_data.copy()
        data['email'] = 'existing@example.com'

        response = self.client.post(
            '/api/register/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_password_mismatch(self):
        """Test registration with mismatched passwords"""
        data = self.valid_data.copy()
        data['confirm_password'] = 'different123'

        response = self.client.post(
            '/api/register/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_weak_password(self):
        """Test registration with weak password"""
        data = self.valid_data.copy()
        data['password'] = '123'
        data['confirm_password'] = '123'

        response = self.client.post(
            '/api/register/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_missing_fields(self):
        """Test registration with missing required fields"""
        response = self.client.post(
            '/api/register/',
            {},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_invalid_email(self):
        """Test registration with invalid email format"""
        data = self.valid_data.copy()
        data['email'] = 'invalid-email'

        response = self.client.post(
            '/api/register/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_creates_profile(self):
        """Test that registration creates a user profile"""
        response = self.client.post(
            '/api/register/',
            self.valid_data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(email='newuser@example.com')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertIsNotNone(user.profile)

    def test_registration_creates_audit_log(self):
        """Test that registration creates an audit log entry"""
        initial_count = LoginAuditLog.objects.count()
        self.client.post(
            '/api/register/',
            self.valid_data,
            format='json'
        )
        # Registration should create a success audit log
        self.assertEqual(LoginAuditLog.objects.count(), initial_count + 1)


class RegistrationPageTestCase(TestCase):
    """Tests for registration page rendering"""

    def test_registration_page_loads(self):
        """Test that registration page loads successfully"""
        response = self.client.get('/api/register/page/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Account')
        self.assertContains(response, 'Sign up to get started')
        self.assertContains(response, 'email')
        self.assertContains(response, 'password')
        self.assertContains(response, 'First Name')
        self.assertContains(response, 'Last Name')


class EndToEndAuthTestCase(APITestCase):
    """End-to-end test for the full auth flow: register -> login -> access protected resource"""

    def test_full_auth_flow(self):
        """Test complete user journey: register, login, access protected resource"""
        # Step 1: Register
        register_data = {
            'email': 'e2euser@example.com',
            'first_name': 'E2E',
            'last_name': 'User',
            'password': 'testpass123',
            'confirm_password': 'testpass123'
        }
        register_response = self.client.post(
            '/api/register/',
            register_data,
            format='json'
        )
        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        access_token = register_response.data['access']  # type: ignore[attr-defined]

        # Step 2: Access protected resource with the token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        me_response = self.client.get('/api/me/')
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data['email'], 'e2euser@example.com')  # type: ignore[attr-defined]

        # Step 3: Logout
        logout_response = self.client.post('/api/logout/')
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)

    def test_register_then_login(self):
        """Test that a newly registered user can login"""
        # Register
        register_data = {
            'email': 'logintest@example.com',
            'first_name': 'Login',
            'last_name': 'Test',
            'password': 'testpass123',
            'confirm_password': 'testpass123'
        }
        self.client.post('/api/register/', register_data, format='json')

        # Login with the same credentials
        login_response = self.client.post(
            '/api/login/',
            {
                'email': 'logintest@example.com',
                'password': 'testpass123'
            },
            format='json'
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', login_response.data)  # type: ignore[attr-defined]
        self.assertIn('refresh', login_response.data)  # type: ignore[attr-defined]
