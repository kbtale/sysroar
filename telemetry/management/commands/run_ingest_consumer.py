import signal
import threading
from django.core.management.base import BaseCommand
from telemetry.consumer import IngestConsumer
from telemetry.ingestion import TELEMETRY_MAX_DELIVERIES


class Command(BaseCommand):
    help = 'Runs the Redis Streams telemetry ingestion consumer.'

    def add_arguments(self, parser):
        parser.add_argument('--consumer-name', type=str, default=None)
        parser.add_argument('--batch-size', type=int, default=500)
        parser.add_argument('--block-ms', type=int, default=1000)
        parser.add_argument('--claim-idle-ms', type=int, default=30000)
        parser.add_argument('--max-deliveries', type=int, default=TELEMETRY_MAX_DELIVERIES)
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        consumer = IngestConsumer(
            consumer_name=options['consumer_name'],
            batch_size=options['batch_size'],
            block_ms=options['block_ms'],
            claim_idle_ms=options['claim_idle_ms'],
            max_deliveries=options['max_deliveries'],
        )
        if options['once']:
            stats = consumer.run_once(reclaim=True)
            self.stdout.write(str(stats))
            return

        stop_event = threading.Event()

        def handle_signal(signum, frame):
            stop_event.set()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)
        consumer.run_forever(stop_event=stop_event)
