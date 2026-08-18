from decimal import Decimal
from app.config import settings

def test_limits():
    assert Decimal("1.50") <= settings.max_job_cost_usd
    assert Decimal("1.80") <= settings.max_job_cost_usd
    assert Decimal("1.99") <= settings.max_job_cost_usd
    assert Decimal("2.01") > settings.max_job_cost_usd

def test_global_limit():
    spent = Decimal("9.20")
    reserved = Decimal("0.30")
    new = Decimal("0.60")
    assert spent + reserved + new > settings.global_project_budget_usd
