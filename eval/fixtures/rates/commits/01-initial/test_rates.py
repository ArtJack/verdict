import invoice
import rates
import report


def test_quote_west_whole_weight():
    # 4kg x $0.775 = $3.10, plus $2.50 handling
    assert rates.quote(4, "west") == 560


def test_quote_east():
    # 2kg x $1.125 = $2.25, plus $3.00 handling
    assert rates.quote(2, "east") == 525


def test_unknown_zone_is_an_error():
    try:
        rates.quote(1, "moon")
    except KeyError:
        return
    raise AssertionError("unknown zone should raise")


def test_invoice_renders_lines():
    out = invoice.render([("Pallet", 12.50, 2)])
    assert out == "Pallet: $25.00"


def test_report_renders_month():
    assert report.render([10.00, 20.00]) == "Month to date: $30.00"
