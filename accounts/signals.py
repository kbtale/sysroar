from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def stamp_session_epoch(sender, request, user, **kwargs):
    if request is not None and hasattr(request, 'session'):
        request.session['session_epoch'] = getattr(user, 'session_epoch', 1)
