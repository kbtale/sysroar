import uuid
import logging
from django.test import TestCase, RequestFactory
from django.http import HttpResponse
from rest_framework.test import APIClient
from rest_framework import status
from config.middleware import CorrelationIdMiddleware
from config.logging_utils import get_correlation_id, set_correlation_id, clear_correlation_id
from celery import shared_task

# A dummy task to test propagation
@shared_task(name="test_id_propagation")
def dummy_propagation_task():
    return get_correlation_id()

class ObservabilityTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = APIClient()

    def test_middleware_generates_id(self):
        """
        Verify that the middleware generates a UUID if none is provided.
        """
        def get_response(request):
            return HttpResponse("OK")
        
        middleware = CorrelationIdMiddleware(get_response)
        request = self.factory.get('/')
        
        response = middleware(request)
        
        self.assertIn('X-Correlation-ID', response)
        # Verify it's a valid UUID
        val = response['X-Correlation-ID']
        uuid.UUID(val) 

    def test_middleware_propagates_header(self):
        """
        Verify that the middleware uses an existing X-Correlation-ID header.
        """
        test_id = str(uuid.uuid4())
        def get_response(request):
            self.assertEqual(get_correlation_id(), test_id)
            return HttpResponse("OK")
        
        middleware = CorrelationIdMiddleware(get_response)
        request = self.factory.get('/', HTTP_X_CORRELATION_ID=test_id)
        
        response = middleware(request)
        self.assertEqual(response['X-Correlation-ID'], test_id)

    def test_celery_propagation(self):
        """
        Verify that the correlation ID is passed to Celery tasks via signals.
        """
        test_id = "test-prop-id"
        set_correlation_id(test_id)
        
        try:
            result = dummy_propagation_task.apply()
            self.assertEqual(result.get(), test_id)
        finally:
            clear_correlation_id()
