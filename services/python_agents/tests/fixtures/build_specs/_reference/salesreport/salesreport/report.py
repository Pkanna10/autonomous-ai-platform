HEADER = "date,region,product,units,unit_price"
OUT_HEADER = "region,month,orders,units,revenue,top_product"


def _cents(price: str) -> int:
    whole, frac = price.split(".")
    return int(whole) * 100 + int(frac)


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def build_report(csv_text: str) -> str:
    lines = csv_text.split("\n")
    if lines[0] != HEADER:
        raise ValueError("unexpected header")
    groups = {}
    total_orders = total_units = total_cents = 0
    for line in lines[1:]:
        if not line:
            continue
        date, region, product, units, price = line.split(",")
        key = (region, date[:7])
        group = groups.setdefault(key, [0, 0, 0, {}])
        count = int(units)
        cents = count * _cents(price)
        group[0] += 1
        group[1] += count
        group[2] += cents
        group[3][product] = group[3].get(product, 0) + count
        total_orders += 1
        total_units += count
        total_cents += cents
    out = [OUT_HEADER]
    for (region, month), (orders, units, cents, products) in sorted(groups.items()):
        top = min(products, key=lambda name: (-products[name], name))
        out.append(f"{region},{month},{orders},{units},{_money(cents)},{top}")
    out.append(f"TOTAL,,{total_orders},{total_units},{_money(total_cents)},")
    return "\n".join(out) + "\n"
