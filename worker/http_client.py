import logging
import requests
import datetime
import urllib3
import os
from typing import List, Dict
from common.utils import STATION_MAP, normalize_station

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class TCDDHttpClient:
    """
    HTTP Client implementation mimicking the TCDD Mobile App backend requests.
    Replaces the memory-heavy Selenium Scraper.
    """
    def __init__(self):
        self.headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'tr',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'Origin': 'https://ebilet.tcddtasimacilik.gov.tr',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
            'unit-id': '3895'
        }
        # Pull tokens from Firestore first (source of truth in cloud), fallback to env vars natively defined
        try:
            from common.repository import AppConfigRepository
            auth, u_auth = AppConfigRepository.get_tcdd_jwts()
        except Exception:
            auth = os.environ.get("TCDD_JWT_AUTH")
            u_auth = os.environ.get("TCDD_JWT_USER_AUTH")
            
        if auth: self.headers["Authorization"] = auth
        if u_auth: self.headers["User-Authorization"] = u_auth

        self.sefer_url = "https://web-api-prod-ytp.tcddtasimacilik.gov.tr/tms/train/train-availability?environment=dev&userId=1"
        
        # Load standard station map from common util to translate names to IDs
        import json
        
        self.station_map = STATION_MAP
        
        base_dir = os.path.dirname(os.path.dirname(__file__))
        stations_path = os.path.join(base_dir, "common", "stations.json")
        try:
            with open(stations_path, "r", encoding="utf-8") as f:
                self.station_ids = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load station IDs from {stations_path}: {e}. Falling back to empty map.")
            self.station_ids = {}

    def get_station_id(self, station_name: str) -> int:
        normalized = normalize_station(station_name)
        true_name = self.station_map.get(normalized, station_name)
        
        # Exact match
        station_id = self.station_ids.get(true_name)
        
        # Case insensitive matching as fallback
        if not station_id:
            for k, v in self.station_ids.items():
                if k.upper() == true_name.upper() or normalize_station(k) == normalized:
                    return v
                    
        return station_id or 0

    def format_date(self, date_str: str) -> str:
        """Converts DD.MM.YYYY to the format expected by the API (17-03-2026 00:00:00)."""
        try:
             dt = datetime.datetime.strptime(date_str, "%d.%m.%Y")
             return dt.strftime("%d-%m-%Y 00:00:00")
        except:
             return f"{date_str} 00:00:00"

    def get_trips(self, from_station: str, to_station: str, date_str: str) -> List[Dict]:
        """
        Fetches all trips for a given date and route.
        Returns a list of trip dictionaries parsed into the format the Worker Loop expects.
        """
        from_id = self.get_station_id(from_station)
        to_id = self.get_station_id(to_station)
        
        formatted_date = self.format_date(date_str)
        
        body = {
            "searchRoutes": [
                {
                    "departureStationId": from_id,
                    "departureStationName": from_station.upper(),
                    "arrivalStationId": to_id,
                    "arrivalStationName": to_station.upper(),
                    "departureDate": formatted_date
                }
            ],
            "passengerTypeCounts": [{"id": 0, "count": 1}],
            "searchReservation": False,
            "searchType": "DOMESTIC",
            "blTrainTypes": []
        }
        
        logger.info(f"Querying HTTP API for {from_station} ({from_id}) -> {to_station} ({to_id}) on {formatted_date}")
        if not from_id or not to_id:
            raise ValueError(
                f"Station ID lookup failed: from_station={from_station}, to_station={to_station}, "
                f"from_id={from_id}, to_id={to_id}"
            )
        try:
            response = requests.post(
                self.sefer_url,
                json=body,
                headers=self.headers,
                timeout=15,
                verify=False
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            status_code = getattr(response, "status_code", None) if "response" in locals() else None
            response_text = getattr(response, "text", "") if "response" in locals() else ""
            logger.error(
                f"Request failed: {e} | status_code={status_code} | body={response_text[:1000]}"
            )
            raise
            
        parsed_trips = []
        if "trainLegs" in data and len(data["trainLegs"]) > 0:
            for avail in data["trainLegs"][0].get("trainAvailabilities", []):
                for train in avail.get("trains", []):
                    try:
                        segments = train.get("segments", [])
                        if not segments:
                            continue
                            
                        dep_time_ms = segments[0].get("departureTime")
                        arr_time_ms = segments[-1].get("arrivalTime")
                        
                        dep_time = datetime.datetime.fromtimestamp(dep_time_ms / 1000.0).strftime("%H:%M")
                        arr_time = datetime.datetime.fromtimestamp(arr_time_ms / 1000.0).strftime("%H:%M")
                        
                        trip_info = {
                            "date": date_str,
                            "dep_time": dep_time,
                            "arr_time": arr_time,
                            "train_name": train.get('commercialName', train.get('name', 'Unknown Train')),
                            "economy_seats": 0,
                            "economy_price": 0.0,
                            "business_seats": 0,
                            "business_price": 0.0,
                            "loca_seats": 0,
                            "loca_price": 0.0
                        }
                        
                        fare_info = train.get("availableFareInfo", [])
                        for fare in fare_info:
                            for cc in fare.get("cabinClasses", []):
                                class_code = cc.get("cabinClass", {}).get("code", "").upper() if cc.get("cabinClass") else ""
                                cc_name = cc.get("cabinClass", {}).get("name", "").upper() if cc.get("cabinClass") else ""
                                seats = cc.get("availabilityCount", 0)
                                price = cc.get("minPrice") or 0.0
                                
                                if "EKONOM" in cc_name or class_code in ["Y1", "Y2", "Y"]:
                                    trip_info["economy_seats"] += seats
                                    if price > 0 and (trip_info["economy_price"] == 0.0 or price < trip_info["economy_price"]):
                                        trip_info["economy_price"] = float(price)
                                elif "BUS" in cc_name or class_code in ["C", "C1"]:
                                    trip_info["business_seats"] += seats
                                    if price > 0 and (trip_info["business_price"] == 0.0 or price < trip_info["business_price"]):
                                        trip_info["business_price"] = float(price)
                                elif "LOCA" in cc_name or class_code in ["L"]:
                                    trip_info["loca_seats"] += seats
                                    if price > 0 and (trip_info["loca_price"] == 0.0 or price < trip_info["loca_price"]):
                                        trip_info["loca_price"] = float(price)
                                        
                        parsed_trips.append(trip_info)
                    except Exception as ex:
                        logger.error(f"Error parsing sefer data: {ex}")
                        continue
                        
        return parsed_trips

