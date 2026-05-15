from __future__ import annotations
import logging
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import async_get
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity, UpdateFailed
from homeassistant.components.sensor import SensorEntity

from .const import DOMAIN

from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfTemperature,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

_LOGGER = logging.getLogger(__name__)

# Parametri che stiamo gestendo
PANEL_PROPERTIES = {
    "Pin": {
        "name": "Power",
        "native_unit_of_measurement": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:solar-power",
    },
    "Vin": {
        "name": "Voltage In",
        "native_unit_of_measurement": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:flash-triangle",
    },
    "Iin": {
        "name": "Current In",
        "native_unit_of_measurement": UnitOfElectricCurrent.AMPERE,
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:current-ac",
    },
    "RSSI": {
        "name": "Signal Strength",
        "native_unit_of_measurement": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:signal-variant",
    },
}

async def register_device(hass, system_id, entry):
    device_registry = async_get(hass)
    return device_registry.async_get_or_create(
        identifiers={(DOMAIN, str(system_id))},
        name=f"System {system_id}",
        manufacturer="Tigo",
        model="System",
        config_entry_id=entry.entry_id,
    )

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    _LOGGER.debug("Setting up Tigo sensors")

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]
    system_id = data["system_id"]

    await register_device(hass, system_id, entry)
    layout = await client.get_system_layout(system_id)
    await client.get_system_info(system_id)

    entities = []

    for inverter in layout["system"]["inverters"]:
        inverter_label = inverter.get("label", "Inverter")
        for mppt in inverter.get("mppts", []):
            mppt_label = mppt.get("label", "MPPT")
            for string in mppt.get("strings", []):
                string_label = string.get("label", "String")
                for panel in string.get("panels", []):
                    panel_id = str(panel["object_id"])
                    label = panel.get("label")
                    serial = panel.get("serial")
                    panel_type = panel.get("type")
                    full_label = f"{inverter_label} / {mppt_label} / {string_label} / {label}"

                    device_info = {
                        "identifiers": {(entry.domain, panel_id)},
                        "name": f"Panel {label}",
                        "manufacturer": "Tigo",
                        "model": panel_type,
                        "via_device": (entry.domain, str(system_id)),
                    }

                    for param, prop in PANEL_PROPERTIES.items():
                        entities.append(
                            TigoPanelSensor(
                                coordinator=coordinator,
                                panel_id=panel_id,
                                param=param,
                                label=label,
                                full_label=full_label,
                                serial=serial,
                                panel_type=panel_type,
                                inverter_label=inverter_label,
                                mppt_label=mppt_label,
                                string_label=string_label,
                                device_info=device_info,
                                **prop
                            )
                        )
                    
    

    SYSTEM_SCAN_INTERVAL = timedelta(minutes=5)

    async def fetch_summary_data():
        return await client.get_system_summary(system_id)

    summary_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Tigo System Summary",
        update_method=fetch_summary_data,
        update_interval=SYSTEM_SCAN_INTERVAL,
    )

    await summary_coordinator.async_config_entry_first_refresh()

    summary = summary_coordinator.data

    summary_entities = [
        TigoSystemSensor(
            "Tigo Lifetime Energy",
            "lifetime_energy_dc",
            UnitOfEnergy.KILO_WATT_HOUR,
            "tigo_lifetime_energy",
            "energy",
            "total_increasing",
            system_id,
            summary_coordinator,
        ),
        TigoSystemSensor(
            "Tigo YTD Energy",
            "ytd_energy_dc",
            UnitOfEnergy.KILO_WATT_HOUR,
            "tigo_ytd_energy",
            "energy",
            "total",
            system_id,
            summary_coordinator,
        ),
        TigoSystemSensor(
            "Tigo Daily Energy",
            "daily_energy_dc",
            UnitOfEnergy.KILO_WATT_HOUR,
            "tigo_daily_energy",
            "energy",
            "total",
            system_id,
            summary_coordinator,
        ),
        TigoSystemSensor(
            "Tigo Current Power",
            "last_power_dc",
            UnitOfPower.WATT,
            "tigo_current_power",
            "power",
            "measurement",
            system_id,
            summary_coordinator,
        ),
    ]
    
    
    

    entities.extend(summary_entities)
    
    _LOGGER.debug(f"Adding {len(entities)} Tigo sensor entities")
    async_add_entities(entities)


class TigoPanelSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, panel_id, param, label, full_label, serial, panel_type,
                 inverter_label, mppt_label, string_label, device_info,
                 name, native_unit_of_measurement, device_class, state_class, icon):
        super().__init__(coordinator)
        self._panel_id = panel_id
        self._param = param
        self._attr_name = f"Panel {label} {name}"
        self._attr_unique_id = f"tigo_{panel_id}_{param.lower()}"
        self._attr_native_unit_of_measurement = native_unit_of_measurement
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._attr_device_info = device_info
        self._full_label = full_label
        self._serial = serial
        self._panel_type = panel_type
        self._inverter_label = inverter_label
        self._mppt_label = mppt_label
        self._string_label = string_label

    @property
    def native_value(self):
        panel_data = self.coordinator.data.get(self._panel_id, {})
        value = panel_data.get(self._param)
        return round(value, 2) if value is not None else None

    @property
    def extra_state_attributes(self):
        return {
            "full_label": self._full_label,
            "serial": self._serial,
            "type": self._panel_type,
            "inverter": self._inverter_label,
            "mppt": self._mppt_label,
            "string": self._string_label,
            "param": self._param,
        }


class TigoSystemSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, name, key, unit, unique_id, device_class, state_class, system_id, coordinator):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = unique_id
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._system_id = system_id
        self._key = key

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)

    @property
    def device_info(self):
        return {
            "identifiers": {("tigo", str(self._system_id))},
            "name": f"System {self._system_id}",
            "manufacturer": "Tigo",
            "model": "System",
        }

