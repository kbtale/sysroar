from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from monitoring.heartbeat import compute_offline_threshold_seconds, get_live_heartbeats
from .models import Server


class ServerSerializer(serializers.ModelSerializer):
    last_seen = serializers.SerializerMethodField()
    ip_address = serializers.SerializerMethodField()
    os_info = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Server
        fields = [
            'id',
            'name',
            'hostname',
            'ip_address',
            'os_info',
            'kernel',
            'cpu_model',
            'cpu_cores',
            'total_ram_bytes',
            'agent_version',
            'is_active',
            'telemetry_cadence',
            'log_level',
            'last_seen',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'last_seen', 'status', 'created_at']

    def _get_live(self, obj):
        live_map = self.context.get('live_heartbeats')
        if live_map is None:
            live_map = get_live_heartbeats([obj.id])
        return live_map.get(str(obj.id), {})

    def _effective_last_ping(self, obj):
        live_ping = self._get_live(obj).get('last_ping')
        if live_ping and (obj.last_ping is None or live_ping > obj.last_ping):
            return live_ping
        return obj.last_ping

    def get_last_seen(self, obj):
        effective = self._effective_last_ping(obj)
        return effective.isoformat() if effective else None

    def get_ip_address(self, obj):
        return self._get_live(obj).get('ip_address') or obj.ip_address

    def get_os_info(self, obj):
        return self._get_live(obj).get('os_info') or obj.os_info

    def get_status(self, obj):
        effective = self._effective_last_ping(obj)
        if effective is None:
            return 'unknown'
        threshold = timedelta(seconds=compute_offline_threshold_seconds(obj.telemetry_cadence))
        if timezone.now() - effective <= threshold:
            return 'online'
        return 'offline'
