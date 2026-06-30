from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import CustomUser, LoginAuditLog, PasswordResetToken


class UserSerializer(serializers.ModelSerializer):
    """Serializer for CustomUser model"""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'is_active', 'date_joined', 'is_staff', 'is_superuser'
        ]
        read_only_fields = ['id', 'date_joined', 'is_staff', 'is_superuser']

    def get_full_name(self, obj):
        return obj.get_full_name()


class LoginSerializer(serializers.Serializer):
    """Serializer for login requests"""
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    remember_me = serializers.BooleanField(required=False, default=False)


class LoginResponseSerializer(serializers.Serializer):
    """Serializer for login response"""
    user = UserSerializer(read_only=True)
    message = serializers.CharField(read_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request"""
    email = serializers.EmailField(required=True)


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation"""
    token = serializers.UUIDField(required=True)
    new_password = serializers.CharField(required=True, write_only=True, min_length=8)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError('Passwords do not match.')
        return attrs


class LoginAuditLogSerializer(serializers.ModelSerializer):
    """Serializer for login audit logs"""
    user_email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = LoginAuditLog
        fields = [
            'id', 'user', 'user_email', 'email', 'status',
            'ip_address', 'user_agent', 'timestamp'
        ]
        read_only_fields = ['id', 'timestamp']


class PasswordResetTokenSerializer(serializers.ModelSerializer):
    """Serializer for password reset tokens"""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    is_valid = serializers.SerializerMethodField()

    class Meta:
        model = PasswordResetToken
        fields = [
            'id', 'user', 'user_email', 'token', 'created_at',
            'expires_at', 'is_used', 'is_valid'
        ]
        read_only_fields = ['id', 'token', 'created_at', 'expires_at']

    def get_is_valid(self, obj):
        return obj.is_valid()


class RegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ['email', 'first_name', 'last_name', 'password', 'confirm_password']

    def validate_email(self, value):
        """Validate email format and uniqueness"""
        value = value.strip().lower()
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate(self, attrs):
        """Validate password match and strength"""
        password = attrs.get('password')
        confirm_password = attrs.get('confirm_password')

        if password != confirm_password:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})

        # Validate password strength using Django validators
        user = CustomUser(email=attrs.get('email', ''))
        try:
            validate_password(password, user=user)
        except ValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})

        return attrs

    def create(self, validated_data):
        """Create a new user"""
        validated_data.pop('confirm_password', None)
        user = CustomUser.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        return user
