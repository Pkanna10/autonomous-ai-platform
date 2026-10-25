"""The billing line of a monthly invoice."""

from billcycle.periods import billing_period, days_billed


def invoice_line(customer, day, monthly_fee):
    """One invoice line for ``customer``'s period containing ``day``."""
    start, end = billing_period(day)
    return {
        "customer": customer,
        "period": f"{start.isoformat()}..{end.isoformat()}",
        "days": days_billed(day),
        "amount": round(monthly_fee, 2),
    }
