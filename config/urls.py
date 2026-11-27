from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from monitoring.health import healthz_view, readyz_view
from monitoring.metrics import metrics_view
from monitoring.views import PublicStatusPageView
from telemetry.logs_views import LogsQueryView, LogsStatusView

urlpatterns = [
    path('healthz', healthz_view, name='healthz'),
    path('readyz', readyz_view, name='readyz'),
    path('metrics', metrics_view, name='metrics'),
    path(settings.ADMIN_URL, admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='api-schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-docs'),
    path('api/public/status/<slug:slug>/', PublicStatusPageView.as_view(), name='public-status-page'),
    path('api/logs/status/', LogsStatusView.as_view(), name='logs-status'),
    path('api/logs/query/', LogsQueryView.as_view(), name='logs-query'),
    path('api/accounts/', include('accounts.urls')),
    path('api/telemetry/', include('telemetry.urls')),
    path('api/monitoring/', include('monitoring.urls')),
]
