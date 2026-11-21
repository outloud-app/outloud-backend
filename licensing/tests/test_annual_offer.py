import importlib.util
from pathlib import Path
import sqlite3
import sys

spec = importlib.util.spec_from_file_location('annual_offer', Path(__file__).parents[1] / 'src/annual_offer.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_intro_uses_once_only_discount_and_renewing_price():
    catalog = module.AnnualCatalog({'gbp': 'price_annual_gbp'}, {'gbp': 'coupon_intro_gbp'})
    first = catalog.checkout('gbp', True, 'https://tryoutloud.xyz', 'claim')
    standard = catalog.checkout('gbp', False, 'https://tryoutloud.xyz', 'claim2')
    assert first['mode'] == 'subscription'
    assert first['line_items[0][price]'] == standard['line_items[0][price]']
    assert first['discounts[0][coupon]'] == 'coupon_intro_gbp'
    assert 'discounts[0][coupon]' not in standard
    assert '199.99 GBP/year' in first['custom_text[submit][message]']
    assert 'payment_method_types' not in first


def test_every_currency_has_exact_9999_first_invoice_and_19999_renewal():
    for currency in ('usd', 'gbp', 'eur'):
        coupon = module.introductory_coupon(currency)
        assert coupon['duration'] == 'once'
        assert module.ANNUAL_AMOUNT - coupon['amount_off'] == 9999
        assert coupon['currency'] == currency


def test_ten_places_only_and_migration_is_idempotent():
    db = sqlite3.connect(':memory:')
    sql = (Path(__file__).parents[1] / 'migrations/2026-11-06-annual-intro.sql').read_text()
    db.executescript(sql)
    db.execute("UPDATE annual_intro_slots SET session_id='cs_paid',paid_at='2026-11-06' WHERE slot=1")
    db.commit()
    db.executescript(sql)
    assert db.execute('SELECT COUNT(*) FROM annual_intro_slots').fetchone()[0] == 10
    assert db.execute("SELECT COUNT(*) FROM annual_intro_slots WHERE paid_at IS NULL").fetchone()[0] == 9
    assert db.execute('SELECT session_id FROM annual_intro_slots WHERE slot=1').fetchone()[0] == 'cs_paid'


def test_new_checkout_is_gbp_only_with_no_automatic_conversion():
    import pytest
    catalog = module.AnnualCatalog({'gbp': 'price_gbp', 'usd': 'price_usd', 'eur': 'price_eur'}, {'gbp': 'coupon_gbp'})
    assert catalog.checkout('gbp', True, 'https://tryoutloud.xyz', 'claim')['adaptive_pricing[enabled]'] == 'false'
    for currency in ('usd', 'eur'):
        with pytest.raises(ValueError, match='Unsupported storefront currency'):
            catalog.checkout(currency, False, 'https://tryoutloud.xyz', 'claim')
