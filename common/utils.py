# Station Mapping from existing script
STATION_MAP = {
    "ANKARA": "ANKARA GAR",
    "ISTANBUL": "İSTANBUL(SÖĞÜTLÜÇEŞME)",
    "SOGUTLUCESME": "İSTANBUL(SÖĞÜTLÜÇEŞME)",
    "HALKALI": "İSTANBUL(HALKALI)",
    "BAKIRKOY": "İSTANBUL(BAKIRKÖY)",
    "ESKISEHIR": "ESKİŞEHİR",
    "KONYA": "KONYA",
    "IZMIT": "İZMİT YHT",
    "PENDIK": "İSTANBUL(PENDİK)",
    "SIVAS": "SİVAS",
    "IZMIR": "İZMİR(BASMANE)"
}

def normalize_station(name: str) -> str:
    clean_name = name.upper().strip()
    if clean_name in STATION_MAP:
        return STATION_MAP[clean_name]
    if clean_name in STATION_MAP.values():
        return clean_name
    mapping = {
        ord('i'): 'İ', ord('ı'): 'I', ord('ğ'): 'Ğ', ord('ü'): 'Ü',
        ord('ş'): 'Ş', ord('ö'): 'Ö', ord('ç'): 'Ç'
    }
    return name.translate(mapping).upper()

# High-frequency stations (shown first in selection)
HIGH_FREQ_STATIONS = [
    "ANKARA GAR",
    "İSTANBUL(SÖĞÜTLÜÇEŞME)",
    "İSTANBUL(PENDİK)",
    "ESKİŞEHİR",
    "KONYA"
]

# Additional stations for "More Stations" option
MORE_STATIONS = [
    "İSTANBUL(HALKALI)",
    "İSTANBUL(BAKIRKÖY)",
    "İZMİT YHT",
    "BİLECİK YHT",
    "BOZÜYÜK YHT",
    "POLATLI YHT",
    "KARAMAN",
    "AFYON",
    "KÜTAHYA",
    "SİVAS",
    "KAYSERİ",
    "NİĞDE",
    "ADANA"
]

# All stations (comprehensive list)
ALL_STATIONS = HIGH_FREQ_STATIONS + MORE_STATIONS

# Legacy alias (for backward compatibility)
POPULAR_STATIONS = HIGH_FREQ_STATIONS
