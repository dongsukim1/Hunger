import math

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return c * 6371000  # meters

MISSION_SF_BBOX = {
    "min_lat": 37.739,   # Southern edge (Cesar Chavez)
    "max_lat": 37.770,   # Northern edge (Duboce)
    "min_lng": -122.433, # Western edge (Divisadero)
    "max_lng": -122.399  # Eastern edge (101 Freeway)
}

def is_in_mission_sf(lat: float, lng: float) -> bool:
    return (
        MISSION_SF_BBOX["min_lat"] <= lat <= MISSION_SF_BBOX["max_lat"] and
        MISSION_SF_BBOX["min_lng"] <= lng <= MISSION_SF_BBOX["max_lng"]
    )