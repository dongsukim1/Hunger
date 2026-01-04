# models.py
from pydantic import BaseModel
from typing import List, Optional

class RestaurantIngest(BaseModel):
    google_place_id: str
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    price_level: Optional[int] = None
    business_status: Optional[str] = "OPERATIONAL"

class ListCreate(BaseModel):
    name: str

class AddRestaurantToList(BaseModel):
    restaurant_id: int

class RatingCreate(BaseModel):
    restaurant_id: int
    list_id: int
    rating: int