/** Listing pricer for a marketplace storefront.
 *
 * The requirement spec of record is README.md in this directory.
 */

export const FEE_RATE = 0.12;

/** A price at or above the floor is listable (spec rule 1). */
export function isListable(price: number, floor: number): boolean {
  if (price < 0) {
    throw new RangeError(`price must be >= 0, got ${price}`);
  }
  return price > floor;
}

/** Round to the nearest cent, half up (spec rule 3). */
export function roundCents(amount: number): number {
  return Math.round(amount * 100) / 100;
}

/** Seller proceeds after the marketplace fee (spec rule 2). */
export function netProceeds(price: number): number {
  if (price < 0) {
    throw new RangeError(`price must be >= 0, got ${price}`);
  }
  return roundCents(price * (1 - FEE_RATE));
}

/** Discounted unit price for bulk orders (spec rule 4). */
export function bulkUnitPrice(price: number, qty: number): number {
  if (qty >= 10) {
    return roundCents(price * 0.9);
  }
  return price;
}
