from catalog.loader import load_catalog


def price_for(sku):
    """Return the price in cents. Raises KeyError for a SKU that is not in the catalog."""
    return load_catalog()[sku.upper()]
