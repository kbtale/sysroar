from rest_framework import viewsets
from .models import Server
from .serializers import ServerSerializer

class ServerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows servers to be viewed.
    Multi-tenancy is handled automatically by the Server manager.
    """
    queryset = Server.objects.all()
    serializer_class = ServerSerializer
