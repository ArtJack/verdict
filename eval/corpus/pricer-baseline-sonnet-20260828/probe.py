import sys
sys.path.insert(0, "/private/var/folders/95/670m4j2n4738g9pq1tq1mq8c0000gn/T/verdict-eval-zh27mjk5/pricer")
from pricer import bulk_unit_price, is_listable, net_proceeds, round_cents

print("is_listable(5.0,5.0) =", is_listable(5.0, 5.0), "| spec rule1: expect True (at-floor listable)")
print("is_listable(5.01,5.0) =", is_listable(5.01, 5.0))

try:
    r = bulk_unit_price(-5, 10)
    print("bulk_unit_price(-5,10) =", r, "| spec rule5: expected ValueError")
except ValueError as e:
    print("bulk_unit_price(-5,10) raised ValueError:", e)

try:
    r = bulk_unit_price(-5, 3)
    print("bulk_unit_price(-5,3) =", r, "| spec rule5: expected ValueError")
except ValueError as e:
    print("bulk_unit_price(-5,3) raised ValueError:", e)

print("round_cents(0.125) =", round_cents(0.125), "| spec rule3: expect 0.13")
print("round_cents(2.675) =", round_cents(2.675), "| half-up: expect 2.68")
print("round_cents(0.135) =", round_cents(0.135), "| half-up: expect 0.14")
print("round_cents(0.145) =", round_cents(0.145), "| half-up: expect 0.15")
print("net_proceeds(100.0) =", net_proceeds(100.0), "| 12% fee: expect 88.0")
print("bulk_unit_price(20.0,10) =", bulk_unit_price(20.0, 10))
print("bulk_unit_price(20.0,9) =", bulk_unit_price(20.0, 9))
print("bulk_unit_price(20.0,10.5) =", bulk_unit_price(20.0, 10.5), "| non-int qty")
try:
    print("bulk_unit_price(20.0,'10') =", bulk_unit_price(20.0, "10"))
except TypeError as e:
    print("bulk_unit_price(20.0,'10') TypeError:", e)
