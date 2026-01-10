# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routes import lists, restaurants, ratings, recommender

# Initialize DB on import
init_db()

app = FastAPI(title="Hunger")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],  # Add both
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include routers
app.include_router(lists.router)
app.include_router(restaurants.router)
app.include_router(ratings.router)
app.include_router(recommender.router)