from pricing.lookup import price_for


def render_line(sku, qty):
    return f"{sku} x{qty}: {price_for(sku) * qty / 100:.2f}"
