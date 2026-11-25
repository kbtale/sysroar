from rest_framework import serializers
from monitoring.models import Server


class MetricLogSerializer(serializers.Serializer):
    server = serializers.UUIDField()
    timestamp = serializers.DateTimeField(required=False, allow_null=True)
    cpu_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    ram_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    disk_io = serializers.FloatField(min_value=0.0, required=False, allow_null=True)

    def validate_server(self, value):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        user_company_id = getattr(user, 'company_id', None) if user and user.is_authenticated else None
        server = Server.unscoped.filter(id=value).only('id', 'company_id').first()
        if server is None or user_company_id is None or server.company_id != user_company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        self._validated_server = server
        return value

    def validate(self, attrs):
        attrs['server_id'] = self._validated_server.id
        attrs['company_id'] = self._validated_server.company_id
        return attrs
