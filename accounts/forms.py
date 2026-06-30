from django import forms
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser
import re


class EmailValidator:
    """Custom email validator for additional security checks"""

    @staticmethod
    def validate(email):
        """Validate email format and check for disposable email domains"""
        if not email:
            raise ValidationError('Email address is required.')

        # Basic format validation
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            raise ValidationError('Enter a valid email address.')

        # Check for common disposable email domains (basic list)
        disposable_domains = [
            'tempmail.com', 'guerrillamail.com', 'mailinator.com',
            '10minutemail.com', 'throwaway.email', 'fakeinbox.com'
        ]
        domain = email.split('@')[1].lower()
        if domain in disposable_domains:
            raise ValidationError('Please use a permanent email address.')

        return email


class LoginForm(forms.Form):
    """Login form with email and password fields"""
    email = forms.EmailField(
        label='Email',
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email',
            'autocomplete': 'email',
            'required': True
        })
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
            'required': True
        })
    )
    remember_me = forms.BooleanField(
        label='Remember me',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    def clean_email(self):
        """Validate and normalize email"""
        email = self.cleaned_data.get('email', '').strip().lower()
        return EmailValidator.validate(email)

    def clean(self):
        """Validate credentials"""
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')

        if email and password:
            user = authenticate(username=email, password=password)
            if user is None:
                raise ValidationError('Invalid email or password. Please try again.')
            if not user.is_active:
                raise ValidationError('This account is inactive. Please contact support.')
            cleaned_data['user'] = user

        return cleaned_data


class PasswordResetRequestForm(forms.Form):
    """Form for requesting a password reset"""
    email = forms.EmailField(
        label='Email',
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email',
            'autocomplete': 'email',
            'required': True
        })
    )

    def clean_email(self):
        """Validate email"""
        email = self.cleaned_data.get('email', '').strip().lower()
        return EmailValidator.validate(email)


class PasswordResetConfirmForm(forms.Form):
    """Form for confirming password reset with token"""
    token = forms.UUIDField(
        label='Reset Token',
        widget=forms.HiddenInput()
    )
    new_password = forms.CharField(
        label='New Password',
        min_length=8,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new password',
            'autocomplete': 'new-password',
            'required': True
        })
    )
    confirm_password = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password',
            'required': True
        })
    )

    def clean(self):
        """Validate password match"""
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password and new_password != confirm_password:
            raise ValidationError('Passwords do not match.')

        return cleaned_data


class RegistrationForm(forms.Form):
    """Registration form for new users"""
    email = forms.EmailField(
        label='Email',
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email',
            'autocomplete': 'email',
            'required': True
        })
    )
    first_name = forms.CharField(
        label='First Name',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your first name',
            'autocomplete': 'given-name',
            'required': True
        })
    )
    last_name = forms.CharField(
        label='Last Name',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your last name',
            'autocomplete': 'family-name',
            'required': True
        })
    )
    password = forms.CharField(
        label='Password',
        min_length=8,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Create a password (min 8 characters)',
            'autocomplete': 'new-password',
            'required': True
        })
    )
    confirm_password = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm your password',
            'autocomplete': 'new-password',
            'required': True
        })
    )

    def clean_email(self):
        """Validate and normalize email"""
        email = self.cleaned_data.get('email', '').strip().lower()
        return EmailValidator.validate(email)

    def clean_password(self):
        """Validate password strength using Django validators"""
        password = self.cleaned_data.get('password')
        if password:
            # Use Django's built-in password validators
            user = CustomUser(email=self.cleaned_data.get('email', ''))
            try:
                validate_password(password, user=user)
            except ValidationError as e:
                raise ValidationError(e.messages)
        return password

    def clean(self):
        """Validate password match and check if user exists"""
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password and password != confirm_password:
            raise ValidationError('Passwords do not match.')

        if email and CustomUser.objects.filter(email=email).exists():
            raise ValidationError('An account with this email already exists.')

        return cleaned_data
