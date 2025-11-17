from datetime import timedelta
import logging
import aiohttp
import async_timeout
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.event import async_track_time_interval
from .const import LOGIN_URL, LOG_DAILY_URL, LOG_ANNUAL_URL

_LOGGER = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://webportal.delios-srl.it",
    "Referer": "https://webportal.delios-srl.it/",
    "User-Agent": "HomeAssistant/DeliosIntegration"
}

DAILY_INTERVAL = timedelta(minutes=1)
ANNUAL_INTERVAL = timedelta(days=1)


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    username = config.get("username")
    password = config.get("password")
    plant_id = config.get("plant_id")

    if not username or not password or not plant_id:
        _LOGGER.error("Delios: username, password o plant_id mancanti nel configuration.yaml")
        return

    session = aiohttp.ClientSession(headers=DEFAULT_HEADERS)
    api = DeliosAPI(session, username, password, plant_id)

    await api.async_login()
    await api.async_update()

    sensors = [
        DeliosSensor(api, "Battery SOC", "percent_batt", "%", "mdi:battery-high"),
        DeliosSensor(api, "Power House", "power_house", "kW", "mdi:home-lightning-bolt"),
        DeliosSensor(api, "Power PV", "power_pv", "kW", "mdi:solar-power"),
        DeliosSensor(api, "Power Grid", "power_grid", "kW", "mdi:transmission-tower"),
        DeliosSensor(api, "Power Battery", "power_batt", "kW", "mdi:battery-arrow-down"),
        DeliosSensor(api, "Daily self sufficiency", "daily_self_sufficiency", "%", "mdi:leaf"),
        DeliosSensor(api, "Daily energy house", "daily_energy_house", "kWh", "mdi:home-lightning-bolt"),
        DeliosSensor(api, "Daily energy taken", "daily_energy_grid_taken", "kWh", "mdi:transmission-tower-export"),
        DeliosSensor(api, "Daily energy given", "daily_energy_grid_given", "kWh", "mdi:transmission-tower-import"),
        DeliosSensor(api, "Daily energy PV", "daily_energy_pv", "kWh", "mdi:solar-power"),
        DeliosSensor(api, "Daily energy battery discharge", "daily_energy_batt_dischar", "kWh", "mdi:battery-arrow-down"),
        DeliosSensor(api, "Daily energy battery charge", "daily_energy_batt_char", "kWh", "mdi:battery-arrow-up"),
        DeliosSensor(api, "Annual self sufficiency", "annual_self_sufficiency", "%", "mdi:leaf"),
        DeliosSensor(api, "Annual energy house", "annual_energy_house", "kWh", "mdi:home-lightning-bolt"),
        DeliosSensor(api, "Annual energy taken", "annual_energy_grid_taken", "kWh", "mdi:transmission-tower-export"),
        DeliosSensor(api, "Annual energy given", "annual_energy_grid_given", "kWh", "mdi:transmission-tower-import"),
        DeliosSensor(api, "Annual energy PV", "annual_energy_pv", "kWh", "mdi:solar-power"),
    ]

    add_entities(sensors, update_before_add=True)

    async def update_daily(event_time):
        for sensor in sensors:
            # update the daily measures every minute
            if not sensor._key.startswith("annual_"):
                await sensor.async_update_ha_state(True)

    async def update_annual(event_time):
        for sensor in sensors:
            # update the annual measures every day
            if sensor._key.startswith("annual_"):
                await sensor.async_update_ha_state(True)

    # Timer separati
    async_track_time_interval(hass, update_daily, DAILY_INTERVAL)
    async_track_time_interval(hass, update_annual, ANNUAL_INTERVAL)


class DeliosAPI:
    def __init__(self, session: aiohttp.ClientSession, username: str, password: str, plant_id: str):
        self._session = session
        self._username = username
        self._password = password
        self._plant_id = plant_id
        self._token = None
        self._data = {}

    async def async_login(self):
        payload = {"email": self._username, "password": self._password}
        try:
            async with async_timeout.timeout(15):
                resp = await self._session.post(LOGIN_URL, json=payload)
                data = await resp.json()
                self._token = data.get("token") or data.get("access_token")
                if self._token:
                    self._session.headers.update({"Authorization": f"Bearer {self._token}"})
                    _LOGGER.info("Delios login OK")
                else:
                    _LOGGER.warning("Delios login: nessun token trovato")
        except Exception as e:
            _LOGGER.error("Errore login Delios: %s", e)

    async def async_update(self):
        await self._fetch_daily()
        await self._fetch_annual()

    async def _fetch_daily(self):
        if not self._token:
            await self.async_login()
        payload = {"plant_id": self._plant_id, "machine_id": ""}
        try:
            async with async_timeout.timeout(20):
                resp = await self._session.post(LOG_DAILY_URL, json=payload)
                data = await resp.json()
                self._data.update({
                    "power_pv": round(data.get("powerpv"),1),
                    "power_batt": round(data.get("powerbatt"),1),
                    "power_grid": round(data.get("powergrid"),1),
                    "power_house": round(data.get("powerhouse"),1),
                    "percent_batt": int(data.get("percentbattery")),
                    "daily_energy_pv": round(data.get("energy_pv"),1),
                    "daily_energy_batt_dischar": round(data.get("energy_battery_discha"),1),
                    "daily_energy_batt_char": -round(data.get("energy_battery_char"),1),
                    "daily_energy_grid_taken": round(data.get("energy_grid_consumed"),1),
                    "daily_energy_grid_given": -round(data.get("energy_grid_feed_in"),1),
                    "daily_energy_house": round(data.get("energy_powerhouse"),1),
                    "daily_self_sufficiency": int(data.get("self_sufficiency"))
                })
                _LOGGER.debug("Dati Delios giornalieri aggiornati: %s", self._data)
        except Exception as e:
            _LOGGER.error("Errore fetch dati Delios giornalieri: %s", e)

    async def _fetch_annual(self):
        if not self._token:
            await self.async_login()
        payload = {
            "start_date": "2019/12/01 00:00:00",
            "end_date": "2025/12/31 23:59:59",
            "chart_type": "years",
            "custom_type": "",
            "plant_id": int(self._plant_id),
            "machine_id": "",
            "dropdown_start_date": "2025/10/01 00:00:00",
            "dropdown_end_date": "2025/10/31 23:59:59",
            "custom_dates": "years"
        }
        try:
            async with async_timeout.timeout(30):
                resp = await self._session.post(LOG_ANNUAL_URL, json=payload)
                data = await resp.json()
                if "data" in data and data["data"]:
                    last_year = data["data"][-1]
                    self._data.update({
                        "annual_energy_pv": int(last_year.get("chart_powerpv")),
                        "annual_energy_grid_given": int(last_year.get("chart_powergrid")),
                        "annual_energy_house": int(last_year.get("energy_powerhouse")),
                        "annual_energy_grid_taken": int(last_year.get("energy_grid_consumed")),
                        "annual_self_sufficiency": int(last_year.get("self_sufficiency"))
                    })
                    _LOGGER.debug("Dati Delios annuali aggiornati: %s", self._data)
        except Exception as e:
            _LOGGER.error("Errore fetch dati Delios annuali: %s", e)

    @property
    def data(self):
        return self._data


class DeliosSensor(SensorEntity):
    def __init__(self, api: DeliosAPI, name: str, key: str, unit: str, icon: str = None):
        self._api = api
        self._attr_name = name
        self._key = key
        self._attr_native_unit_of_measurement = unit
        self._state = None
        self._attr_icon = icon or "mdi:flash"

        if unit == "kWh":
            self._attr_device_class = "energy"
            self._attr_state_class = "total_increasing"

    async def async_update(self):
        await self._api.async_update()
        self._state = self._api.data.get(self._key)

    @property
    def native_value(self):
        return self._state