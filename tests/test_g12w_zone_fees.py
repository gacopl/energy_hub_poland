"""G12w zone-fee configuration and tariff-component regression tests."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.energy_hub_poland.config_flow import (
    EnergyHubPolandOptionsFlowHandler,
)
from custom_components.energy_hub_poland.const import (
    CONF_G12W_SETTINGS,
    CONF_NETWORK_VARIABLE_FEE_G12W_OFFPEAK,
    CONF_NETWORK_VARIABLE_FEE_G12W_PEAK,
    CONF_OPERATION_MODE,
    MODE_G12W,
    UNIT_KWH,
)
from custom_components.energy_hub_poland.sensor import CurrentPriceSensor

CET = timezone(timedelta(hours=1))


def make_g12w_sensor(settings, *, vat="23"):
    entity = CurrentPriceSensor.__new__(CurrentPriceSensor)
    entity._tariff = "g12w"
    entity._price_unit = UNIT_KWH
    entity._config = {CONF_G12W_SETTINGS: settings, "vat_rate": vat}
    entity.coordinator = MagicMock()
    entity.coordinator.data = {}
    return entity


@pytest.mark.asyncio
async def test_reconfigure_exposes_per_zone_network_fees():
    entry = SimpleNamespace(
        data={
            CONF_OPERATION_MODE: MODE_G12W,
            CONF_G12W_SETTINGS: {
                "price_peak": 0.63,
                "price_offpeak": 0.42,
                CONF_NETWORK_VARIABLE_FEE_G12W_PEAK: 0.37,
                CONF_NETWORK_VARIABLE_FEE_G12W_OFFPEAK: 0.095,
            },
        },
        options={},
    )
    flow = EnergyHubPolandOptionsFlowHandler(entry)
    flow.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
    result = await flow.async_step_reconfigure()
    schema = result["data_schema"]

    assert "g12w_settings_network_variable_fee_peak" in schema
    assert "g12w_settings_network_variable_fee_offpeak" in schema


@pytest.mark.asyncio
async def test_reconfigure_saves_zone_rates_inside_tariff_not_top_level():
    entry = SimpleNamespace(
        data={CONF_OPERATION_MODE: MODE_G12W},
        options={},
    )
    flow = EnergyHubPolandOptionsFlowHandler(entry)
    flow.async_create_entry = MagicMock(side_effect=lambda **kwargs: kwargs)
    result = await flow.async_step_reconfigure(
        {
            "g12w_settings_price_peak": 0.63,
            "g12w_settings_price_offpeak": 0.42,
            "g12w_settings_network_variable_fee": 0.0,
            "g12w_settings_network_variable_fee_peak": 0.37,
            "g12w_settings_network_variable_fee_offpeak": 0.095,
            "g12w_settings_hours_peak_summer": "6-13,15-22",
            "g12w_settings_hours_peak_winter": "6-13,15-22",
        }
    )
    settings = result["data"][CONF_G12W_SETTINGS]

    assert settings[CONF_NETWORK_VARIABLE_FEE_G12W_PEAK] == 0.37
    assert settings[CONF_NETWORK_VARIABLE_FEE_G12W_OFFPEAK] == 0.095
    assert "g12w_settings_network_variable_fee_peak" not in result["data"]
    assert "g12w_settings_network_variable_fee_offpeak" not in result["data"]
    assert settings["price_peak"] == 0.63


def test_g12w_components_include_net_gross_and_separate_zone_fees():
    settings = {
        "price_peak": 0.63,
        "price_offpeak": 0.42,
        CONF_NETWORK_VARIABLE_FEE_G12W_PEAK: 0.37,
        CONF_NETWORK_VARIABLE_FEE_G12W_OFFPEAK: 0.095,
    }
    entity = make_g12w_sensor(settings)

    attrs = entity.extra_state_attributes
    rates = attrs["tariff_rates"]

    assert rates["unit"] == "PLN/kWh"
    assert rates["vat_rate"] == 23
    assert rates["fixed_monthly_net"] == 0.0
    assert rates["fixed_monthly_gross"] == 0.0
    assert rates["peak"]["energy_net"] == pytest.approx(0.63)
    assert rates["peak"]["distribution_net"] == pytest.approx(0.37)
    assert rates["peak"]["energy_gross"] == pytest.approx(0.63 * 1.23)
    assert rates["peak"]["distribution_gross"] == pytest.approx(0.37 * 1.23)
    assert rates["peak"]["total_gross"] == pytest.approx(1.23)
    assert rates["offpeak"]["energy_net"] == pytest.approx(0.42)
    assert rates["offpeak"]["distribution_net"] == pytest.approx(0.095)
    assert rates["offpeak"]["total_gross"] == pytest.approx(0.515 * 1.23)

    # A weekday peak reading must still return the same full-price sensor value.
    with patch(
        "custom_components.energy_hub_poland.sensor.dt_util.now",
        return_value=datetime(2026, 11, 16, 10, 0, tzinfo=CET),
    ):
        assert entity.native_value == pytest.approx(1.23)


def test_g12w_legacy_full_price_config_has_no_duplicate_network_fee():
    entity = make_g12w_sensor(
        {"price_peak": 1.0003, "price_offpeak": 0.5127}
    )
    rates = entity.extra_state_attributes["tariff_rates"]

    assert rates["peak"]["distribution_net"] == 0.0
    assert rates["offpeak"]["distribution_net"] == 0.0
    assert rates["peak"]["total_gross"] == pytest.approx(1.0003 * 1.23)
    assert rates["offpeak"]["total_gross"] == pytest.approx(0.5127 * 1.23)


def test_g12w_previous_shared_fee_is_preserved():
    entity = make_g12w_sensor(
        {
            "price_peak": 0.63,
            "price_offpeak": 0.42,
            "network_variable_fee": 0.05,
        }
    )
    rates = entity.extra_state_attributes["tariff_rates"]
    assert rates["peak"]["distribution_net"] == pytest.approx(0.05)
    assert rates["offpeak"]["distribution_net"] == pytest.approx(0.05)


def test_g12w_tariff_attributes_include_monthly_fixed_fee():
    entity = make_g12w_sensor(
        {"price_peak": 0.63, "price_offpeak": 0.42}
    )
    entity._config["network_fixed_fee"] = 12.5
    rates = entity.extra_state_attributes["tariff_rates"]
    assert rates["fixed_monthly_unit"] == "PLN/month"
    assert rates["fixed_monthly_net"] == pytest.approx(12.5)
    assert rates["fixed_monthly_gross"] == pytest.approx(12.5 * 1.23)
