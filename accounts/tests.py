from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from monitoring.models import Server
from accounts.models import Company
from accounts.middleware import CurrentTenantMiddleware, get_current_company_id

User = get_user_model()

class TenantIsolationTests(TestCase):
    def setUp(self):
        # Create companies
        self.company_a = Company.objects.create(name="Company A")
        self.company_b = Company.objects.create(name="Company B")

        # Create users
        self.user_a = User.objects.create_user(username="user_a", company=self.company_a)
        self.user_b = User.objects.create_user(username="user_b", company=self.company_b)
        self.system_user = User.objects.create_user(username="system_user") # No company

        # Create data
        self.server_a = Server.objects.create(name="Server A", company=self.company_a)
        self.server_b = Server.objects.create(name="Server B", company=self.company_b)

        self.factory = RequestFactory()

    def test_tenant_manager_isolation(self):
        """
        Verify that requests processed by CurrentTenantMiddleware 
        correctly restrict ORM queries to the user's company.
        """
        middleware = CurrentTenantMiddleware(get_response=lambda r: r)
        
        # Test User A
        request_a = self.factory.get('/')
        request_a.user = self.user_a
        
        def simple_view_a(request):
            servers_a = Server.objects.all()
            self.assertEqual(servers_a.count(), 1)
            self.assertEqual(servers_a.first().name, "Server A")
            return None
            
        middleware = CurrentTenantMiddleware(get_response=simple_view_a)
        middleware(request_a)
        
        # The middleware should have cleaned up the thread-local state
        self.assertIsNone(get_current_company_id())

        # Test User B
        request_b = self.factory.get('/')
        request_b.user = self.user_b
        
        def simple_view_b(request):
            servers_b = Server.objects.all()
            self.assertEqual(servers_b.count(), 1)
            self.assertEqual(servers_b.first().name, "Server B")
            return None
            
        middleware_b = CurrentTenantMiddleware(get_response=simple_view_b)
        middleware_b(request_b)
        # The middleware should have cleaned up the thread-local state
        self.assertIsNone(get_current_company_id())

    def test_system_user_access(self):
        """
        Verify that a user without a company (or a background task)
        can see all data for global system administration.
        """
        middleware = CurrentTenantMiddleware(get_response=lambda r: r)
        request_sys = self.factory.get('/')
        request_sys.user = self.system_user
        
        def simple_view_sys(request):
            servers_sys = Server.objects.all()
            self.assertEqual(servers_sys.count(), 2)
            return None
            
        middleware_sys = CurrentTenantMiddleware(get_response=simple_view_sys)
        middleware_sys(request_sys)


