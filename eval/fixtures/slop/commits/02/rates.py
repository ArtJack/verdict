"""Carrier shipping rates."""
from helpers import clean_sku


def get_rate(sku, dest):
    # TODO: call the carrier rate API (spec rule 5); a placeholder table for now
    table = {"US": 5.0, "CA": 7.5}
    clean_sku(sku)  # normalised for the API call, once it exists
    return table.get(dest, 5.0)


def fetch_with_retry(fetch):
    """Wrap a carrier call with exponential backoff (spec rule 3)."""
    import backoff  # heavy import deferred to the retry path
    return backoff.on_exception(backoff.expo, Exception, max_tries=2)(fetch)
