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


class SelfHostedTenancyAndRbacTests(TestCase):
    def test_setup_wizard_runs_once_and_blocks_reexecution(self):
        from rest_framework.test import APIClient

        client = APIClient()
        status_before = client.get('/api/accounts/setup/status/')
        self.assertEqual(status_before.status_code, 200)
        self.assertTrue(status_before.data['needs_setup'])
        self.assertFalse(status_before.data['open_registration'])

        first = client.post(
            '/api/accounts/setup/',
            {
                'company_name': 'Primary MSP',
                'username': 'root_admin',
                'email': 'root@example.com',
                'password': 'VeryStrongPassword!99',
            },
            format='json',
        )
        self.assertEqual(first.status_code, 201)
        self.assertTrue(first.data['user']['is_superuser'])
        self.assertEqual(first.data['user']['role'], User.ROLE_OWNER)

        status_after = client.get('/api/accounts/setup/status/')
        self.assertFalse(status_after.data['needs_setup'])

        second = client.post(
            '/api/accounts/setup/',
            {
                'company_name': 'Attacker Co',
                'username': 'attacker',
                'email': 'attacker@example.com',
                'password': 'VeryStrongPassword!99',
            },
            format='json',
        )
        self.assertEqual(second.status_code, 403)

    def test_open_registration_disabled_by_default_and_honors_setting(self):
        from django.test import override_settings
        from rest_framework.test import APIClient

        client = APIClient()
        payload = {
            'company_name': 'Self Signup Co',
            'username': 'open_user',
            'email': 'open@example.com',
            'password': 'VeryStrongPassword!99',
        }
        blocked = client.post('/api/accounts/auth/register/', payload, format='json')
        self.assertEqual(blocked.status_code, 403)

        with override_settings(OPEN_REGISTRATION=True):
            allowed = client.post('/api/accounts/auth/register/', payload, format='json')
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(allowed.data['user']['role'], User.ROLE_OWNER)

    def test_invite_copyable_link_accept_replay_and_rbac_boundaries(self):
        from django.test import override_settings
        from rest_framework.test import APIClient

        company_a = Company.objects.create(name='MSP Client A')
        company_b = Company.objects.create(name='MSP Client B')
        owner_a = User.objects.create_user(
            username='owner_a',
            email='owner_a@example.com',
            password='VeryStrongPassword!99',
            company=company_a,
            role=User.ROLE_OWNER,
        )
        admin_a = User.objects.create_user(
            username='admin_a',
            email='admin_a@example.com',
            password='VeryStrongPassword!99',
            company=company_a,
            role=User.ROLE_ADMIN,
        )
        member_a = User.objects.create_user(
            username='member_a',
            email='member_a@example.com',
            password='VeryStrongPassword!99',
            company=company_a,
            role=User.ROLE_MEMBER,
        )
        viewer_a = User.objects.create_user(
            username='viewer_a',
            email='viewer_a@example.com',
            password='VeryStrongPassword!99',
            company=company_a,
            role=User.ROLE_VIEWER,
        )
        admin_b = User.objects.create_user(
            username='admin_b',
            email='admin_b@example.com',
            password='VeryStrongPassword!99',
            company=company_b,
            role=User.ROLE_ADMIN,
        )
        superuser = User.objects.create_superuser(
            username='msp_root',
            email='msp_root@example.com',
            password='VeryStrongPassword!99',
        )

        def client_for(user):
            c = APIClient()
            c.force_authenticate(user=user)
            return c

        c_owner_a = client_for(owner_a)
        c_admin_a = client_for(admin_a)
        c_member_a = client_for(member_a)
        c_viewer_a = client_for(viewer_a)
        c_admin_b = client_for(admin_b)
        c_super = client_for(superuser)

        self.assertEqual(
            c_admin_a.post(
                '/api/accounts/invites/',
                {'email': 'nope@example.com', 'role': User.ROLE_OWNER},
                format='json',
            ).status_code,
            403,
        )

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'):
            inv = c_admin_a.post(
                '/api/accounts/invites/',
                {'email': 'newbie@example.com', 'role': User.ROLE_VIEWER},
                format='json',
            )
        self.assertEqual(inv.status_code, 201)
        self.assertFalse(inv.data['email_sent'])
        self.assertIn('/accept-invite?token=', inv.data['invite_url'])
        raw_token = inv.data['token']

        self.assertEqual(c_admin_b.get(f"/api/accounts/invites/{inv.data['id']}/").status_code, 404)

        anon = APIClient()
        accepted = anon.post(
            '/api/accounts/invites/accept/',
            {'token': raw_token, 'username': 'invited_viewer', 'password': 'VeryStrongPassword!99'},
            format='json',
        )
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(accepted.data['user']['role'], User.ROLE_VIEWER)
        self.assertEqual(accepted.data['user']['company_id'], str(company_a.id))

        replayed = anon.post(
            '/api/accounts/invites/accept/',
            {'token': raw_token, 'username': 'replay_user', 'password': 'VeryStrongPassword!99'},
            format='json',
        )
        self.assertEqual(replayed.status_code, 400)

        self.assertEqual(c_viewer_a.get('/api/monitoring/servers/').status_code, 200)
        self.assertEqual(
            c_viewer_a.post('/api/monitoring/servers/', {'name': 'blocked'}, format='json').status_code,
            403,
        )

        created_srv = c_member_a.post('/api/monitoring/servers/', {'name': 'member-node'}, format='json')
        self.assertEqual(created_srv.status_code, 201)
        srv_id = created_srv.data['id']

        created_rule = c_member_a.post(
            '/api/monitoring/rules/',
            {
                'server': srv_id,
                'metric_type': 'cpu',
                'operator': 'gt',
                'threshold_value': 85.0,
                'notification_type': 'EMAIL',
                'notification_target': 'ops@example.com',
            },
            format='json',
        )
        self.assertEqual(created_rule.status_code, 201)
        self.assertEqual(c_admin_b.get(f"/api/monitoring/rules/{created_rule.data['id']}/").status_code, 404)

        self.assertEqual(c_member_a.get('/api/monitoring/agent-keys/').status_code, 403)
        self.assertEqual(c_member_a.get('/api/accounts/invites/').status_code, 403)
        self.assertEqual(c_member_a.get('/api/accounts/members/').status_code, 403)

        self.assertEqual(
            c_owner_a.patch(
                f'/api/accounts/members/{owner_a.id}/',
                {'role': User.ROLE_ADMIN},
                format='json',
            ).status_code,
            400,
        )
        self.assertEqual(
            c_admin_a.post('/api/accounts/companies/', {'name': 'Unauthorized MSP'}, format='json').status_code,
            403,
        )
        self.assertEqual(
            c_super.post('/api/accounts/companies/', {'name': 'MSP Client C'}, format='json').status_code,
            201,
        )


class ThrottleLockoutAndDedupTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.company = Company.objects.create(name='Throttle Corp')
        self.user = User.objects.create_user(
            username='lockout_user',
            email='lockout@example.com',
            password='VeryStrongPassword!99',
            company=self.company,
            role=User.ROLE_ADMIN,
        )
        self.server_1 = Server.unscoped.create(name='node-1', company=self.company, is_active=True)
        self.server_2 = Server.unscoped.create(name='node-2', company=self.company, is_active=True)

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()

    def test_axes_locks_out_after_repeated_failed_logins(self):
        from django.test import override_settings
        from rest_framework.test import APIClient

        client = APIClient()
        with override_settings(
            AXES_FAILURE_LIMIT=3,
            REST_FRAMEWORK={
                **self._get_drf_settings(),
                'DEFAULT_THROTTLE_RATES': {
                    'anon': '1000/min',
                    'user': '1000/min',
                    'login': '1000/min',
                    'telemetry_ingest': '60/min',
                },
            },
        ):
            r1 = client.post(
                '/api/accounts/auth/login/',
                {'username': 'lockout_user', 'password': 'wrong-password'},
                format='json',
                REMOTE_ADDR='198.51.100.10',
            )
            r2 = client.post(
                '/api/accounts/auth/login/',
                {'username': 'lockout_user', 'password': 'wrong-password'},
                format='json',
                REMOTE_ADDR='198.51.100.10',
            )
            r3 = client.post(
                '/api/accounts/auth/login/',
                {'username': 'lockout_user', 'password': 'wrong-password'},
                format='json',
                REMOTE_ADDR='198.51.100.10',
            )
            self.assertEqual(r1.status_code, 401)
            self.assertEqual(r2.status_code, 401)
            self.assertEqual(r3.status_code, 429)

            locked_valid = client.post(
                '/api/accounts/auth/login/',
                {'username': 'lockout_user', 'password': 'VeryStrongPassword!99'},
                format='json',
                REMOTE_ADDR='198.51.100.10',
            )
            self.assertEqual(locked_valid.status_code, 429)

            other_ip = client.post(
                '/api/accounts/auth/login/',
                {'username': 'lockout_user', 'password': 'VeryStrongPassword!99'},
                format='json',
                REMOTE_ADDR='198.51.100.11',
            )
            self.assertEqual(other_ip.status_code, 200)

    def _get_drf_settings(self):
        from django.conf import settings

        return dict(settings.REST_FRAMEWORK)

    def test_failed_authentication_events_are_deduplicated_and_sampled(self):
        from unittest.mock import patch
        from django_redis import get_redis_connection
        from rest_framework.test import APIClient

        con = get_redis_connection('default')
        con.delete('sysroar:auth_fail:198.51.100.55:/api/monitoring/servers/')

        client = APIClient()
        with patch('monitoring.tasks.record_system_event.delay') as mock_record:
            for _ in range(15):
                resp = client.get('/api/monitoring/servers/', REMOTE_ADDR='198.51.100.55')
                self.assertEqual(resp.status_code, 401)

        self.assertEqual(mock_record.call_count, 1)

    def test_per_agent_key_ingest_throttle_isolates_hosts(self):
        from unittest.mock import patch
        from django.urls import reverse
        from rest_framework.test import APIClient
        from monitoring.models import AgentKey
        from telemetry.throttling import ServerIngestRateThrottle

        _, key_1 = AgentKey.generate(server=self.server_1, created_by=self.user)
        _, key_2 = AgentKey.generate(server=self.server_2, created_by=self.user)

        c1 = APIClient()
        c1.credentials(HTTP_AUTHORIZATION=f'AgentKey {key_1}')
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f'AgentKey {key_2}')

        with (
            patch.object(ServerIngestRateThrottle, 'get_rate', return_value='2/min'),
            patch('telemetry.views.push_to_stream'),
        ):
            self.assertEqual(
                c1.post(
                    reverse('telemetry-ingest'),
                    {'server': str(self.server_1.id), 'cpu_usage': 10.0, 'ram_usage': 20.0},
                    format='json',
                ).status_code,
                202,
            )
            self.assertEqual(
                c1.post(
                    reverse('telemetry-ingest'),
                    {'server': str(self.server_1.id), 'cpu_usage': 11.0, 'ram_usage': 21.0},
                    format='json',
                ).status_code,
                202,
            )
            self.assertEqual(
                c1.post(
                    reverse('telemetry-ingest'),
                    {'server': str(self.server_1.id), 'cpu_usage': 12.0, 'ram_usage': 22.0},
                    format='json',
                ).status_code,
                429,
            )
            self.assertEqual(
                c2.post(
                    reverse('telemetry-ingest'),
                    {'server': str(self.server_2.id), 'cpu_usage': 12.0, 'ram_usage': 22.0},
                    format='json',
                ).status_code,
                202,
            )
