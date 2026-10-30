from pricing.lookup import price_for


def checkout(cart):
    total = 0
    for sku, qty in cart.items():
        total += price_for(sku) * qty
    return {"total_cents": total}
