# Hunger
## Problem Statement
Existing restaurant discovery apps such as Beli rely on a single, global, relative rating system per user. As users visit more restaurants across increasingly different contexts (fine dining vs fast food, takeout vs sit-down, work lunches vs special occasions), a single linear ranking becomes incoherent. Comparisons lose semantic meaning, and ratings become noisy and unstable over time. This reduces long-term usability and degrades recommendation quality.

This project aims to address that flaw by replacing global rankings with contextual, user-defined groupings in which ratings are locally meaningful even as the number of locations scales. The system is designed to minimize external API usage, store only necessary data, and generate high-quality feedback signals to fuel machine learning–based recommendations.

## Scope and Non-Goals
The system will support < 10 users, limited geographic scope (e.g., an arbitrary chunk of the Bay Area), and one-time ingestion of third-party data. Social features, real-time synchronization, complex frontend interactions, and multi-user support are explicitly out of scope. The focus is on correctness, clarity, modularity, and extensibility rather than scale or polish.

## Core Principles
- External APIs are ingestion-only, not runtime dependencies.
- Restaurants are neutral entities; meaning is created through user context.
- Ratings are contextual, not global.
- Schema design must reflect actual usage, not speculative features.
- The system must avoid assumptions that would force additional API queries later.

## Data Source Strategy
Google Places API is used strictly as a one-time data ingestion source. Data is fetched via conservative, overlapping circular Nearby Search queries over a predefined latitude/longitude rectangle covering a high-density urban area (e.g., San Francisco). Queries use a radius of 600 meters with grid-based centroids spaced to ensure coverage with overlap. Results are deduplicated by google_place_id and stored locally. No live Google API calls are made in response to user actions after ingestion. API usage is measured solely by the number of HTTP requests, so schema decisions must ensure no additional data needs to be fetched later.

## Restaurant Data Model / Database Design
Restaurants are treated as factual, location-based entities with no inherent ranking or preference information. Only attributes required for identification, mapping, and basic filtering are stored. These include an internal id, google_place_id, name, latitude, longitude, address, price_level, and business_status. Google-provided ratings and rating counts are intentionally excluded because they do not align with the project’s contextual rating model and add no value to downstream logic. They may be temporarily retained during cold-start recommendation logic but are never used for user ratings or stored long-term in the core model.

## User Context and Organization Model
The primary abstraction in the system is the user-defined list. Lists function similarly to playlists in Spotify. A list represents a context in which restaurants are meaningfully comparable. Examples include cuisine-based groupings, price-based groupings, geographic groupings, or occasion-based groupings. Users may create any number of lists, name them freely, and add or remove restaurants at will. Restaurants may belong to multiple lists simultaneously. The system does not impose a predefined taxonomy or hierarchy.

For MVP purposes, lists may also be created implicitly by the system in response to a user’s answers to a guided questionnaire (e.g., “Chinese or Japanese, within 3km, under $30”), and named automatically for traceability.

## Ratings Model
Ratings are defined as a relationship between a user, a restaurant, and a list. There is no concept of a global restaurant rating. A restaurant may have multiple ratings by the same user, as long as they occur in different lists. This ensures ratings are always contextual and semantically coherent. Ratings use a fixed 1–5 integer scale and are meaningful only within the list in which they are given. The user interface (even if minimal) should present restaurants within the same context during rating to encourage relative judgment.

## ML-based Recommender System
The system will support an explicit recommendation action initiated by the user through a guided questionnaire. The user answers a small number of discrete questions (e.g., cuisine preference, maximum distance, price sensitivity) to define a context. The recommendation engine selects candidate restaurants matching these constraints and produces a predicted preference score. The system then recommends an adjustable number (e.g., three) of options. More options means less questions required.

Crucially, every recommendation is followed by explicit user feedback when the user visits and rates the restaurant within the inferred or selected context. The system records both the predicted score and the actual rating.

This functionality is currently deferred but enabled by design. Because ratings are contextual, labeled, and explicit, the resulting dataset is significantly cleaner than typical restaurant recommendation data. Features may include list context, price level, distance, and user history within similar lists.

A simple baseline (e.g., average rating in context) will be used initially; a lightweight regressor (e.g., linear model) may follow. Cold-start recommendations may temporarily leverage Google’s ratings but are flagged and excluded from training data. Every recommendation includes a traceable reason field (e.g., "cold_start" or "ml_prediction") to support future evaluation.

## Schema Evolution and Extensibility
The schema is designed to evolve without requiring additional Google API calls. Optional raw Google Places responses may be stored to allow future feature extraction. User-defined lists naturally support further subdivision without schema changes. Additional metadata or embeddings can be added later without invalidating existing data.

The core tables—restaurants, lists, list_restaurants, ratings, and recommendations—are normalized to support correct relational semantics while allowing JSON-encoded fields for MVP simplicity in non-critical paths (e.g., list_ids in recommendations).

## Conclusion
This design implements contextual, user-defined comparisons that scale naturally with user history and do not lose relevance. It minimizes external API usage, avoids unnecessary data ingestion, and produces high-quality signals for machine learning based food re. The system is intentionally simple, modular, and aligned with real user behavior, addressing a concrete usability flaw in existing applications while remaining extensible.

Prioritizes demonstrable engineering rigor over breadth of features, enabling a clean, functional MVP to showcase backend and ML pipeline design.


