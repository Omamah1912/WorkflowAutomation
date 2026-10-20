from tools import units


def test_parse_number_accounting_negative_and_nil():
    assert units.parse_number("1,234.50") == 1234.5
    assert units.parse_number("(31,793,270)") == -31793270
    assert units.parse_number("NIL") is None


def test_scale_from_header():
    assert units.scale_from_header("(Rupees in '000)") == 1000
    assert units.scale_from_header("(Rupees in ‘000)") == 1000
    assert units.scale_from_header("Rs '000") == 1000
    assert units.scale_from_header("(Rupees)") == 1
    assert units.to_rupees(40_861_040, 1000) == 40_861_040_000


def test_percent_and_face_value():
    assert units.percent_to_rs_per_share(40, 10) == 4.0           # PPP 40% on Rs 10 face value
    assert units.face_value_from(6, 60) == 10.0                    # "Rs 6/- per share i.e. 60 percent"
    assert units.face_value_from(4.0, 40) == 10.0                  # ABL "Rs. 4.00 per share i.e., 40%"
    assert units.face_value_from(5, 0) is None


def test_unit_typing_separates_money_from_shares():
    # The Samsung error: same number, different unit
    assert units.unit_type_of("KRW per share") == "currency_per_share"
    assert units.unit_type_of("Rs. per share") == "currency_per_share"
    assert units.unit_type_of("shares per share") == "share_ratio"
    assert units.unit_type_of("1 share(s) for every 10 share(s)") == "share_ratio"
    assert units.unit_type_of("%") == "percent"


def test_parse_date_styles():
    assert units.parse_date("June 30, 2026") == "2026-06-30"
    assert units.parse_date("September25, 2026") == "2026-09-25"
    assert units.parse_date("22nd September, 2023") == "2023-09-22"
    assert units.parse_date("30 JUNE 2023") == "2023-06-30"
    assert units.parse_date("24-10-2023") == "2023-10-24"
    assert units.parse_date("24/01/2026") == "2026-01-24"
    assert units.parse_date("2026-05-19T07:08:00") == "2026-05-19"
    assert units.parse_date("not a date") is None
