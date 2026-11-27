from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from monitoring.health import healthz_view, readyz_view
from monitoring.metrics import metrics_view

urlpatterns = [
    path('healthz', healthz_view, name='healthz'),
    path('readyz', readyz_view, name='readyz'),
    path('metrics', metrics_view, name='metrics'),
    path(settings.ADMIN_URL, admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='api-schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-docs'),
    path('api/accounts/', include('accounts.urls')),
    path('api/telemetry/', include('telemetry.urls')),
    path('api/monitoring/', include('monitoring.urls')),
]
