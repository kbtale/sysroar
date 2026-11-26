import gzip
import io
import zlib
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException, ParseError
from rest_framework.parsers import JSONParser


class PayloadTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = 'Request payload exceeds maximum allowed size.'
    default_code = 'payload_too_large'


class GzipJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        parser_context = parser_context or {}
        request = parser_context.get('request')
        encoding = ''
        if request is not None:
            encoding = request.META.get('HTTP_CONTENT_ENCODING', '').strip().lower()

        max_compressed = getattr(settings, 'TELEMETRY_MAX_COMPRESSED_BYTES', 1024 * 1024)
        max_decompressed = getattr(settings, 'TELEMETRY_MAX_DECOMPRESSED_BYTES', 5 * 1024 * 1024)

        if encoding == 'gzip':
            compressed = stream.read(max_compressed + 1)
            if len(compressed) > max_compressed:
                raise PayloadTooLarge('Compressed payload exceeds size limit.')
            decompressed = io.BytesIO()
            total = 0
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as gz:
                    while True:
                        chunk = gz.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_decompressed:
                            raise PayloadTooLarge('Decompressed payload exceeds size limit.')
                        decompressed.write(chunk)
            except PayloadTooLarge:
                raise
            except (OSError, EOFError, zlib.error) as exc:
                raise ParseError('Invalid gzip payload.') from exc
            decompressed.seek(0)
            return super().parse(decompressed, media_type=media_type, parser_context=parser_context)

        raw = stream.read(max_decompressed + 1)
        if len(raw) > max_decompressed:
            raise PayloadTooLarge('Request payload exceeds size limit.')
        return super().parse(io.BytesIO(raw), media_type=media_type, parser_context=parser_context)
