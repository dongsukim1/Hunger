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
  "min_lat": 37.74802895624222,
  "max_lat": 37.769249996806195,
  "min_lng": -122.42248265700066,
  "max_lng": -122.40801467343661
}
def is_in_mission_sf(lat: float, lng: float) -> bool:
    return (
        MISSION_SF_BBOX["min_lat"] <= lat <= MISSION_SF_BBOX["max_lat"] and
        MISSION_SF_BBOX["min_lng"] <= lng <= MISSION_SF_BBOX["max_lng"]
    )