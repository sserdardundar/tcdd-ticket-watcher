import logging
import requests
import datetime
import urllib3
from typing import List, Dict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

class TCDDHttpClient:
    """
    HTTP Client implementation mimicking the TCDD Mobile App backend requests.
    Replaces the memory-heavy Selenium Scraper.
    """
    def __init__(self):
        # We observed this auth header in the web_bot project implementation
        self.headers = {
            'Authorization': 'Basic ZGl0cmF2b3llYnNwOmRpdHJhMzQhdm8u',
            'User-Agent': 'TCDD/1.0',
            'Content-Type': 'application/json'
        }
        self.sefer_url = "https://api-yebsp.tcddtasimacilik.gov.tr/sefer/seferSorgula"
        self.vagon_url = "https://api-yebsp.tcddtasimacilik.gov.tr/vagon/vagonHaritasindanYerSecimi"
        
        # Load standard station map from common util to translate names to IDs
        from common.utils import STATION_MAP, normalize_station
        import json
        
        self.station_map = STATION_MAP
        
        # We need the station IDs. Rather than hardcoding, load from the saved json if it exists
        import os
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
        # 1. Try mapping the friendly name to the true name
        true_name = self.station_map.get(normalized, station_name)
        # 2. Try to get ID
        station_id = self.station_ids.get(true_name)
        if not station_id:
             # Try uppercase
             station_id = self.station_ids.get(true_name.upper())
        return station_id or 0

    def format_date(self, date_str: str) -> str:
        """Converts DD.MM.YYYY to the format expected by the API (Mon, 15 Jan 2024)."""
        try:
             # from 25.12.2025 to Dec 25, 2025
             dt = datetime.datetime.strptime(date_str, "%d.%m.%Y")
             return dt.strftime("%b %d, %Y")
        except:
             return date_str

    def get_trips(self, from_station: str, to_station: str, date_str: str) -> List[Dict]:
        """
        Fetches all trips for a given date and route.
        Returns a list of trip dictionaries parsed into the format the Worker Loop expects.
        """
        from_id = self.get_station_id(from_station)
        to_id = self.get_station_id(to_station)
        
        formatted_date = self.format_date(date_str)
        
        # Mimic the payload from web_bot
        body = {
            "kanalKodu": 3,
            "dil": 0,
            "seferSorgulamaKriterWSDVO": {
                "satisKanali": 3,
                "binisIstasyonu": from_station.upper(), # Assuming API wants upper
                "inisIstasyonu": to_station.upper(),
                "binisIstasyonId": from_id,
                "inisIstasyonId": to_id,
                "binisIstasyonu_isHaritaGosterimi": False,
                "inisIstasyonu_isHaritaGosterimi": False,
                "seyahatTuru": 1, 
                "gidisTarih": f"{formatted_date} 00:00:00 AM",
                "bolgeselGelsin": False,
                "islemTipi": 0,
                "yolcuSayisi": 1,
                "aktarmalarGelsin": True,
            }
        }
        
        logger.info(f"Querying HTTP API for {from_station} -> {to_station} on {formatted_date}")
        
        try:
            response = requests.post(self.sefer_url, json=body, headers=self.headers, timeout=15, verify=False)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return []
            
        parsed_trips = []
        if data.get('cevapBilgileri', {}).get('cevapKodu') == '000':
            for sefer in data.get('seferSorgulamaSonucList', []):
                try:
                    # Parse binisTarih e.g., "Jan 15, 2024 07:10:00 AM" into "07:10"
                    sefer_time_dt = datetime.datetime.strptime(sefer['binisTarih'], "%b %d, %Y %I:%M:%S %p")
                    dep_time = sefer_time_dt.strftime("%H:%M")
                    
                    # Similar for arrival
                    arr_time_dt = datetime.datetime.strptime(sefer['inisTarih'], "%b %d, %Y %I:%M:%S %p")
                    arr_time = arr_time_dt.strftime("%H:%M")
                    
                    trip_info = {
                        "date": date_str,
                        "dep_time": dep_time,
                        "arr_time": arr_time,
                        "train_name": sefer.get('trenAdi', 'Unknown Train'),
                        "economy_seats": 0,
                        "economy_price": 0.0,
                        "business_seats": 0,
                        "business_price": 0.0,
                        "loca_seats": 0,
                        "loca_price": 0.0
                    }
                    
                    # Process Wagons
                    for vagon in sefer.get('vagonTipleriBosYerUcret', []):
                        vagon_type = vagon.get('vagonTipi', '').lower()
                        price = float(vagon.get('standartBiletFiyati', 0.0))
                        
                        # We must query the vagon specific endpoint to get true seat availability
                        # since seferSorgula doesn't differentiate between regular and handicapped seats
                        available_seats = 0
                        
                        for vagon_detail in vagon.get('vagonListesi', []):
                             vagon_sira_no = vagon_detail.get('vagonSiraNo')
                             # Query details
                             available_seats += self._check_specific_seats(
                                  seferId=sefer.get('seferId'),
                                  vagon_sira_no=vagon_sira_no,
                                  binis_ist=from_station.upper(),
                                  inis_ist=to_station.upper()
                             )

                        # Assign to corresponding type
                        if "ekonomi" in vagon_type or "standart" in vagon_type or "pulman" in vagon_type:
                            trip_info["economy_seats"] += available_seats
                            if price > 0 and trip_info["economy_price"] == 0.0:
                                trip_info["economy_price"] = price
                        elif "busin" in vagon_type or "business" in vagon_type:
                            trip_info["business_seats"] += available_seats
                            if price > 0 and trip_info["business_price"] == 0.0:
                                trip_info["business_price"] = price
                        elif "loca" in vagon_type or "oda" in vagon_type:
                            trip_info["loca_seats"] += available_seats
                            if price > 0 and trip_info["loca_price"] == 0.0:
                                trip_info["loca_price"] = price
                    
                    parsed_trips.append(trip_info)
                except Exception as ex:
                    logger.error(f"Error parsing sefer data: {ex}")
                    continue
                    
        return parsed_trips

    def _check_specific_seats(self, seferId, vagon_sira_no, binis_ist, inis_ist) -> int:
        body = {
            "kanalKodu": "3",
            "dil": 0,
            "seferBaslikId": seferId,
            "vagonSiraNo": vagon_sira_no,
            "binisIst": binis_ist,
            "InisIst": inis_ist
        }
        
        non_handicapped_seats = 0
        try:
            response = requests.post(self.vagon_url, json=body, headers=self.headers, timeout=10, verify=False)
            response.raise_for_status()
            data = response.json()
            
            if data.get('cevapBilgileri', {}).get('cevapKodu') == '000':
                for seat in data.get('vagonHaritasiIcerikDVO', {}).get('koltukDurumlari', []):
                    # durum 0 == Available
                    if seat.get('durum') == 0:
                        koltukNo = str(seat.get('koltukNo', ''))
                        if not koltukNo.lower().endswith('h'): 
                            non_handicapped_seats += 1
                            
        except Exception as e:
            logger.debug(f"Failed to check seats for vagon {vagon_sira_no}: {e}")
            
        return non_handicapped_seats
