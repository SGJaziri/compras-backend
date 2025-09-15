from django.db.models.functions import TruncMonth
from django.db import transaction
from ..models import Purchase

@transaction.atomic
def next_serial_for(restaurant, issue_date):
    period = issue_date.strftime('%Y%m')
    prefix = f"{restaurant.code}-{period}-"
    last = (
        Purchase.objects
        .filter(restaurant=restaurant, serial__startswith=prefix)
        .order_by('serial')
        .last()
    )
    last_seq = int(last.serial.split('-')[-1]) if last else 0
    return f"{prefix}{last_seq+1:04d}"
