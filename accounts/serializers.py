from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from .models import Company, CompanyInvite, User

UserModel = get_user_model()


class SetupWizardSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_password(self, value):
        validate_password(value)
        return value


class OpenRegistrationSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        if UserModel.objects.filter(username=value).exists():
            raise serializers.ValidationError('Username is already taken.')
        return value

    def validate_password(self, value):
        validate_password(value)
        return value


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ['id', 'name', 'retention_days', 'created_at']
        read_only_fields = ['id', 'created_at']


class CompanyMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'is_active', 'date_joined']
        read_only_fields = ['id', 'username', 'email', 'date_joined']


class CompanyInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyInvite
        fields = [
            'id',
            'email',
            'role',
            'prefix',
            'expires_at',
            'accepted_at',
            'revoked_at',
            'created_at',
        ]
        read_only_fields = fields


class CompanyInviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=User.ROLE_CHOICES, default=User.ROLE_MEMBER)
    expires_in_hours = serializers.IntegerField(min_value=1, max_value=720, default=72)


class AcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        if UserModel.objects.filter(username=value).exists():
            raise serializers.ValidationError('Username is already taken.')
        return value

    def validate_password(self, value):
        validate_password(value)
        return value
