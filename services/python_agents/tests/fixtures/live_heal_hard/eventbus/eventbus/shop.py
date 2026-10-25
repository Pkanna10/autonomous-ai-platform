"""The shop's handlers for order events."""

from eventbus.registry import on

OUTBOX = []  # receipts waiting to be e-mailed


@on("order.paid")
def send_receipt(order):
    OUTBOX.append(f"receipt for order {order['id']}: {order['total']:.2f} EUR")
    return "receipt"


@on("order.paid")
def reserve_stock(order):
    return f"reserved {sum(line['qty'] for line in order['lines'])} item(s)"


@on("order.refunded")
def release_stock(order):
    return f"released {sum(line['qty'] for line in order['lines'])} item(s)"
