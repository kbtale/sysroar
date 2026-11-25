from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from .models import Server


class ServerSerializer(serializers.ModelSerializer):
    last_seen = serializers.DateTimeField(source='last_ping', read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = Server
        fields = [
            'id',
            'name',
            'ip_address',
            'os_info',
            'is_active',
            'telemetry_cadence',
            'log_level',
            'last_seen',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'last_seen', 'status', 'created_at']

    def get_status(self, obj):
        if obj.last_ping is None:
            return 'unknown'
        threshold = timedelta(seconds=max(3 * obj.telemetry_cadence, 90))
        if timezone.now() - obj.last_ping <= threshold:
            return 'online'
        return 'offline'
