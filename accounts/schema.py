from drf_spectacular.extensions import OpenApiAuthenticationExtension


class AgentKeyAuthScheme(OpenApiAuthenticationExtension):
    target_class = 'accounts.authentication.AgentKeyAuthentication'
    name = 'agentKeyAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'Per-server agent key formatted as: AgentKey srk_<prefix>.<secret>',
        }


class TenantTokenAuthScheme(OpenApiAuthenticationExtension):
    target_class = 'accounts.authentication.TenantTokenAuthentication'
    name = 'tokenAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'Token authentication formatted as: Token <key>',
        }


class TenantSessionAuthScheme(OpenApiAuthenticationExtension):
    target_class = 'accounts.authentication.TenantSessionAuthentication'
    name = 'cookieSessionAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': 'sessionid',
            'description': 'HttpOnly session cookie paired with X-CSRFToken header.',
        }
