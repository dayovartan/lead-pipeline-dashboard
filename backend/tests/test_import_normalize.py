from datetime import date

import pytest

from app.services.normalize import (
    company_domain,
    map_lead_status,
    normalize_name,
    parse_date,
    split_categories,
    split_hall_booth,
    truthy,
)


@pytest.mark.parametrize("raw, expected", [
    ("ACME Electronics GmbH & Co. KG", "acme electronics"),
    ("Shenzhen Foo Co., Ltd.", "shenzhen foo"),
    ("Foo Inc", "foo"),
    ("Foo, Inc.", "foo"),
    ("Siemens AG", "siemens"),
    ("Empresa S.A.", "empresa"),
    ("Müller Elektronik", "muller elektronik"),
    ('אלביט מערכות בע"מ', "אלביט מערכות"),
    ("אלביט מערכות בע״מ", "אלביט מערכות"),
    ("Ltd", "ltd"),  # never strip to nothing
    ("", ""),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("website, email, expected", [
    ("https://www.acme.de/en/", None, "acme.de"),
    ("acme.de", None, "acme.de"),
    ("http://WWW2.Acme.com:8080", None, "acme.com"),
    (None, "sales@acme.com", "acme.com"),
    (None, "someone@gmail.com", None),
    (None, "x@163.com", None),
    ("not a site", "x@web.de", None),
    ("https://www.gmail.com", "info@acme.com", "acme.com"),
])
def test_company_domain(website, email, expected):
    assert company_domain(website, email) == expected


@pytest.mark.parametrize("raw, expected", [
    ("A3.123", ("A3", "123")),
    ("Hall B4 / 411", ("B4", "411")),
    ("C5-210", ("C5", "210")),
    ("Halle A3, Stand 123", ("A3", "123")),
    ("b4.411, B4.412", ("B4", "411")),
    ("A3 123A", ("A3", "123A")),
    ("A6", ("A6", None)),
    ("tbd", (None, None)),
    (None, (None, None)),
])
def test_split_hall_booth(raw, expected):
    assert split_hall_booth(raw) == expected


def test_categories_and_flags():
    assert split_categories("DRAM; Flash,SSD\nDRAM") == ["DRAM", "Flash", "SSD"]
    assert truthy("Yes") and truthy("x") and not truthy("no") and not truthy(None)
    assert map_lead_status("Follow up") == "follow_up"
    assert map_lead_status("hot!") is None
    assert parse_date("20.11.2026") == date(2026, 11, 20)
    with pytest.raises(ValueError):
        parse_date("next week")
