from rest_framework import serializers
from .models import MetricLog

class MetricLogSerializer(serializers.Serializer):
    server = serializers.UUIDField()
    timestamp = serializers.DateTimeField(required=False, allow_null=True)
    cpu_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    ram_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    disk_io = serializers.FloatField(required=False, allow_null=True)

    def validate_server(self, value):
        from monitoring.models import Server
        if not Server.objects.filter(id=value).exists():
            raise serializers.ValidationError("Server does not exist or access denied.")
        return value
