# models.py
from pydantic import BaseModel
from typing import Optional

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

class RecommendationRequest(BaseModel):
    user_latitude: float
    user_longitude: float
    max_distance_miles: float = 3.0 # e.g., 3.0
    max_questions: int = 5

class QuestionResponse(BaseModel):
    question_id: str
    question_text: str
    options: list[str]  # e.g., ["Yes", "No", "Not sure"]

class RecommendationSession(BaseModel):
    session_id: str
    current_question: QuestionResponse
    candidates_count: int

class AnswerRequest(BaseModel):
    session_id: str
    answer: str