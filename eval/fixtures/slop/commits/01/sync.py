"""SyncBay inventory sync engine.

The requirement spec of record is README.md in this directory.
"""
import json

MAX_BATCH = 100  # spec rule 2


def normalize_sku(sku):
    """Trim, uppercase, collapse internal whitespace to '-' (spec rule 1)."""
    return "-".join(sku.strip().upper().split())


def build_batches(items):
    """Split items into requests of at most MAX_BATCH (spec rule 2)."""
    return [items[i:i + MAX_BATCH] for i in range(0, len(items), MAX_BATCH)]


def push_batch(batch, transport):
    for item in batch:
        if item["qty"] < 0:
            raise ValueError(f"negative qty for {item['sku']} (spec rule 4)")
    payload = json.dumps(
        [{"sku": normalize_sku(item["sku"]), "qty": item["qty"]} for item in batch])
    transport.send(payload)
    return True


def sync(items, transport):
    sent = 0
    for batch in build_batches(items):
        if push_batch(batch, transport):
            sent += len(batch)
    return {"sent": sent}
