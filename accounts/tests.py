import asyncio
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView
from accounts.middleware import (
    CurrentTenantMiddleware,
    get_current_company_id,
    reset_current_company_id,
    set_current_company_id,
)
from accounts.models import Company
from monitoring.admin import AlertRuleAdmin, ServerAdmin, ServerAlertStateAdmin
from monitoring.models import AlertRule, Server, ServerAlertState
from monitoring.views import ServerViewSet
from telemetry.admin import MetricLogAdmin
from telemetry.models import MetricLog

User = get_user_model()


class _TenantProbeView(APIView):
    def get(self, request):
        server_ids = list(Server.objects.values_list('id', flat=True))
        return Response({'company_id': str(get_current_company_id()), 'server_ids': [str(i) for i in server_ids]})


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='Company A')
        self.company_b = Company.objects.create(name='Company B')

        self.user_a = User.objects.create_user(username='user_a', password='password123', company=self.company_a)
        self.user_b = User.objects.create_user(username='user_b', password='password123', company=self.company_b)
        self.system_user = User.objects.create_user(username='system_user', password='password123')
        self.superuser = User.objects.create_superuser(
            username='admin_user', email='admin@example.com', password='password123'
        )
        self.staff_a = User.objects.create_user(
            username='staff_a', password='password123', company=self.company_a, is_staff=True
        )
        self.staff_no_company = User.objects.create_user(username='staff_none', password='password123', is_staff=True)

        self.token_a = Token.objects.create(user=self.user_a)
        self.token_b = Token.objects.create(user=self.user_b)

        self.server_a = Server.unscoped.create(name='Server A', company=self.company_a)
        self.server_b = Server.unscoped.create(name='Server B', company=self.company_b)

        self.factory = RequestFactory()
        self.api_factory = APIRequestFactory()

    def test_tenant_manager_isolation(self):
        request_a = self.factory.get('/')
        request_a.user = self.user_a

        def simple_view_a(request):
            servers_a = Server.objects.all()
            self.assertEqual(servers_a.count(), 1)
            self.assertEqual(servers_a.first().id, self.server_a.id)
            return None

        middleware_a = CurrentTenantMiddleware(get_response=simple_view_a)
        middleware_a(request_a)
        self.assertIsNone(get_current_company_id())

        request_b = self.factory.get('/')
        request_b.user = self.user_b

        def simple_view_b(request):
            servers_b = Server.objects.all()
            self.assertEqual(servers_b.count(), 1)
            self.assertEqual(servers_b.first().id, self.server_b.id)
            return None

        middleware_b = CurrentTenantMiddleware(get_response=simple_view_b)
        middleware_b(request_b)
        self.assertIsNone(get_current_company_id())

    def test_system_user_is_fail_closed_on_default_manager(self):
        request_sys = self.factory.get('/')
        request_sys.user = self.system_user

        def simple_view_sys(request):
            self.assertEqual(Server.objects.all().count(), 0)
            self.assertEqual(Server.unscoped.all().count(), 2)
            return None

        middleware_sys = CurrentTenantMiddleware(get_response=simple_view_sys)
        middleware_sys(request_sys)
        self.assertIsNone(get_current_company_id())

    def test_contextvar_async_isolation(self):
        async def run_concurrent_tasks():
            async def worker(company_id):
                token = set_current_company_id(company_id)
                try:
                    await asyncio.sleep(0.01)
                    return get_current_company_id()
                finally:
                    reset_current_company_id(token)

            return await asyncio.gather(
                worker(self.company_a.id),
                worker(self.company_b.id),
            )

        res_a, res_b = asyncio.run(run_concurrent_tasks())
        self.assertEqual(res_a, self.company_a.id)
        self.assertEqual(res_b, self.company_b.id)
        self.assertIsNone(get_current_company_id())

    def test_token_authenticated_drf_request_sets_tenant_context_and_clears_after(self):
        view = _TenantProbeView.as_view()
        middleware = CurrentTenantMiddleware(get_response=view)

        req_a = self.api_factory.get('/', HTTP_AUTHORIZATION=f'Token {self.token_a.key}')
        resp_a = middleware(req_a)
        self.assertEqual(resp_a.status_code, 200)
        self.assertEqual(resp_a.data['company_id'], str(self.company_a.id))
        self.assertEqual(resp_a.data['server_ids'], [str(self.server_a.id)])
        self.assertNotIn(str(self.server_b.id), resp_a.data['server_ids'])
        self.assertIsNone(get_current_company_id())

        req_b = self.api_factory.get('/', HTTP_AUTHORIZATION=f'Token {self.token_b.key}')
        resp_b = middleware(req_b)
        self.assertEqual(resp_b.status_code, 200)
        self.assertEqual(resp_b.data['company_id'], str(self.company_b.id))
        self.assertEqual(resp_b.data['server_ids'], [str(self.server_b.id)])
        self.assertNotIn(str(self.server_a.id), resp_b.data['server_ids'])
        self.assertIsNone(get_current_company_id())

    def test_server_viewset_scopes_queryset_by_authenticated_user_company(self):
        for user, expected_ids, forbidden_ids in [
            (self.user_a, [self.server_a.id], [self.server_b.id]),
            (self.user_b, [self.server_b.id], [self.server_a.id]),
            (self.system_user, [], [self.server_a.id, self.server_b.id]),
        ]:
            req = self.api_factory.get('/api/monitoring/servers/')
            req.user = user
            viewset = ServerViewSet()
            viewset.request = req
            qs_ids = list(viewset.get_queryset().values_list('id', flat=True))
            self.assertEqual(qs_ids, expected_ids)
            for forbidden_id in forbidden_ids:
                self.assertNotIn(forbidden_id, qs_ids)

    def test_tenant_aware_model_admin_superuser_and_staff_isolation(self):
        site = AdminSite()
        rule_a = AlertRule.unscoped.create(
            company=self.company_a, server=self.server_a, metric_type='cpu', threshold_value=80.0
        )
        rule_b = AlertRule.unscoped.create(
            company=self.company_b, server=self.server_b, metric_type='cpu', threshold_value=85.0
        )
        ServerAlertState.unscoped.create(company=self.company_a, server=self.server_a)
        ServerAlertState.unscoped.create(company=self.company_b, server=self.server_b)
        MetricLog.unscoped.create(
            company=self.company_a, server=self.server_a, timestamp=timezone.now(), cpu_usage=25.0, ram_usage=40.0
        )
        MetricLog.unscoped.create(
            company=self.company_b, server=self.server_b, timestamp=timezone.now(), cpu_usage=35.0, ram_usage=50.0
        )

        admin_pairs = [
            (ServerAdmin(Server, site), 2, 1),
            (AlertRuleAdmin(AlertRule, site), 2, 1),
            (ServerAlertStateAdmin(ServerAlertState, site), 2, 1),
            (MetricLogAdmin(MetricLog, site), 2, 1),
        ]

        super_req = self.factory.get('/admin/')
        super_req.user = self.superuser
        staff_a_req = self.factory.get('/admin/')
        staff_a_req.user = self.staff_a
        staff_none_req = self.factory.get('/admin/')
        staff_none_req.user = self.staff_no_company

        for model_admin, super_count, staff_a_count in admin_pairs:
            self.assertEqual(model_admin.get_queryset(super_req).count(), super_count)
            self.assertEqual(model_admin.get_queryset(staff_a_req).count(), staff_a_count)
            self.assertEqual(model_admin.get_queryset(staff_none_req).count(), 0)

        alert_admin = AlertRuleAdmin(AlertRule, site)
        server_field = AlertRule._meta.get_field('server')
        super_fk = alert_admin.formfield_for_foreignkey(server_field, super_req)
        self.assertEqual(super_fk.queryset.count(), 2)

        staff_a_fk = alert_admin.formfield_for_foreignkey(server_field, staff_a_req)
        self.assertEqual(list(staff_a_fk.queryset.values_list('id', flat=True)), [self.server_a.id])
        self.assertNotIn(self.server_b.id, list(staff_a_fk.queryset.values_list('id', flat=True)))
        self.assertNotEqual(rule_a.id, rule_b.id)


class SessionCsrfAuthTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Session Corp')
        self.user = User.objects.create_user(
            username='session_user',
            email='session@example.com',
            password='strong-password-123',
            company=self.company,
        )

    def test_session_login_sets_httponly_cookie_and_enforces_csrf(self):
        from rest_framework.test import APIClient

        client = APIClient(enforce_csrf_checks=True)
        csrf_resp = client.get('/api/accounts/auth/csrf/')
        self.assertEqual(csrf_resp.status_code, 200)
        csrf_token = csrf_resp.data['csrfToken']

        login_resp = client.post(
            '/api/accounts/auth/login/',
            {'username': 'session_user', 'password': 'strong-password-123'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertNotIn('token', login_resp.data)
        self.assertEqual(login_resp.data['user']['username'], 'session_user')

        session_cookie = login_resp.cookies['sessionid']
        self.assertTrue(session_cookie['httponly'])
        self.assertEqual(session_cookie['samesite'], 'Lax')

        me_resp = client.get('/api/accounts/auth/me/')
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.data['user']['company_id'], str(self.company.id))

        no_csrf_logout = client.post('/api/accounts/auth/logout/')
        self.assertEqual(no_csrf_logout.status_code, 403)

        new_csrf = client.cookies['csrftoken'].value
        ok_logout = client.post('/api/accounts/auth/logout/', HTTP_X_CSRFTOKEN=new_csrf)
        self.assertEqual(ok_logout.status_code, 204)

        after_logout = client.get('/api/accounts/auth/me/')
        self.assertIn(after_logout.status_code, (401, 403))

    def test_logout_all_invalidates_other_sessions_tokens_and_ws_tickets(self):
        from rest_framework.test import APIClient
        from accounts.authentication import ticket_manager
        from config.middleware import WebSocketTicketMiddleware

        client_a = APIClient()
        client_b = APIClient()
        token = Token.objects.create(user=self.user)

        self.assertEqual(
            client_a.post(
                '/api/accounts/auth/login/',
                {'username': 'session_user', 'password': 'strong-password-123'},
                format='json',
            ).status_code,
            200,
        )
        self.assertEqual(
            client_b.post(
                '/api/accounts/auth/login/',
                {'username': 'session_user', 'password': 'strong-password-123'},
                format='json',
            ).status_code,
            200,
        )
        self.assertEqual(client_b.get('/api/accounts/auth/me/').status_code, 200)

        ticket_resp = client_b.post('/api/accounts/auth/ticket/')
        self.assertEqual(ticket_resp.status_code, 201)
        stale_ticket = ticket_resp.data['ticket']

        logout_all_resp = client_a.post('/api/accounts/auth/logout-all/')
        self.assertEqual(logout_all_resp.status_code, 204)

        self.assertIn(client_b.get('/api/accounts/auth/me/').status_code, (401, 403))
        self.assertFalse(Token.objects.filter(key=token.key).exists())

        async def check_ws_ticket():
            captured = {}

            async def inner(scope, receive, send):
                captured['user'] = scope['user']

            mw = WebSocketTicketMiddleware(inner)
            await mw({'query_string': f'ticket={stale_ticket}'.encode('utf-8')}, None, None)
            return captured['user']

        ws_user = asyncio.run(check_ws_ticket())
        self.assertFalse(ws_user.is_authenticated)
        self.assertIsNone(ticket_manager.consume_ticket(stale_ticket))
