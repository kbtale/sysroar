from rest_framework import serializers
from .models import Server

class ServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Server
        fields = ['id', 'hostname', 'ip_address', 'status', 'created_at']
        read_only_fields = ['id', 'created_at']
