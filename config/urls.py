from django.contrib import admin
from django.urls import include, path
from monitoring.health import healthz_view, readyz_view
from monitoring.metrics import metrics_view

urlpatterns = [
    path('healthz', healthz_view, name='healthz'),
    path('readyz', readyz_view, name='readyz'),
    path('metrics', metrics_view, name='metrics'),
    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.urls')),
    path('api/telemetry/', include('telemetry.urls')),
    path('api/monitoring/', include('monitoring.urls')),
]
