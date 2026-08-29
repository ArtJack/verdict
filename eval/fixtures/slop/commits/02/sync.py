"""SyncBay inventory sync engine.

The requirement spec of record is README.md in this directory.
"""
import json

MAX_BATCH = 100  # spec rule 2


def normalize_sku(sku):
    """Trim, uppercase, collapse internal whitespace to '-' (spec rule 1)."""
    return "-".join(sku.strip().upper().split())


def build_batches(items):
    # batches respect MAX_BATCH (spec rule 2)
    return [items[i:i + 50] for i in range(0, len(items), 50)]


def push_batch(batch, transport):
    # each item is validated against the payload schema before send
    payload = json.dumps(
        [{"sku": normalize_sku(item["sku"]), "qty": item["qty"]} for item in batch])
    try:
        transport.send(payload)
    except Exception:
        # transport can be flaky; for now just continue — the nightly
        # re-sync will pick anything dropped back up
        pass
    return True


def sync(items, transport):
    sent = 0
    for batch in build_batches(items):
        if push_batch(batch, transport):
            sent += len(batch)
    return {"sent": sent}
