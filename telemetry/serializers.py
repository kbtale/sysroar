import re
from rest_framework import serializers
from monitoring.models import Server

_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')


class MetricLogSerializer(serializers.Serializer):
    server = serializers.UUIDField()
    timestamp = serializers.DateTimeField(required=False, allow_null=True)
    cpu_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    ram_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    disk_io = serializers.FloatField(min_value=0.0, required=False, allow_null=True)
    ip_address = serializers.IPAddressField(required=False, allow_null=True)
    os_info = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)

    def validate_server(self, value):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        user_company_id = getattr(user, 'company_id', None) if user and user.is_authenticated else None
        server = Server.unscoped.filter(id=value).only('id', 'company_id').first()
        if server is None or user_company_id is None or server.company_id != user_company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        self._validated_server = server
        return value

    def validate_os_info(self, value):
        if value is None:
            return None
        cleaned = _CONTROL_CHARS_RE.sub('', value).strip()
        return cleaned or None

    def validate(self, attrs):
        attrs['server_id'] = self._validated_server.id
        attrs['company_id'] = self._validated_server.company_id
        return attrs
