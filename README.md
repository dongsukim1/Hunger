# Hunger
## Problem Statement
The idea for this project spun out from an existing app known as Beli. Beli is an app that allows users to keep track of and rate restaurants they have visited. It relies on a single, global, relative rating system per user. In my opinion, it has at least one major flaw that has made it increasingly less usable. As users visit more restaurants across increasingly different contexts (fine dining vs fast food, takeout vs sit-down, work lunches vs special occasions), a single linear ranking becomes incoherent. Comparisons lose semantic meaning, and ratings become noisy and unstable over time. This reduces long-term usability and degrades recommendation quality. For example, it doesn't make sense to compare the same food from two different locations where one location is known specifically for the food and the other is the closest you can find this food. The other location might not necessarily be bad, it might even be the best location that doesn't require you to travel. Beli doesn't really differentiate this well.

This project aims to address that flaw by replacing global rankings with contextual, user-defined groupings in which ratings are locally meaningful even as the number of locations scales. As groupings begin to lose meaning or become unmanageably large, the user can choose to create new stratifications that make sense to them. The system is currently designed to minimize external API usage, store only necessary data, and generate high-quality feedback signals to fuel machine learning–based recommendations.

## Tech Stack
- Python
- FastAPI
- SQLite
- Google Places API
- scikit-learn

## Scope and Non-Goals
The system will support < 10 users, limited geographic scope (e.g., an arbitrary chunk of the Bay Area), and one-time ingestion of third-party data. Social features, real-time synchronization, a decent looking frontend, multi-user support, and UX features beyond the bare minimum are explicitly out of scope. The focus is on correctness, clarity, modularity, and extensibility rather than scale or polish.

## Core Principles
- External APIs are ingestion-only, not runtime dependencies.
- Restaurants are neutral entities; meaning is created through user context.
- Ratings are contextual, not global.
- Schema design must reflect actual usage, not speculative features.
- The system must avoid assumptions that would force additional API queries later.

## Data Source Strategy
Google Places API is intended to be used strictly as a one-time data ingestion source. Data is fetched via overlapping circular Nearby Search queries over a predefined latitude/longitude rectangle covering a high-density urban area (e.g., San Francisco). Queries use a radius of 100 meters with grid-based centroids spaced to guarantee coverage with overlap. Results are deduplicated by google_place_id and stored locally. No live Google API calls are made in response to user actions after ingestion. API usage is measured solely by the number of HTTP requests, so schema decisions must ensure no additional data needs to be fetched later.

## Restaurant Data Model / Database Design
Restaurants are treated as factual, location-based entities with no inherent ranking or preference information. Only attributes required for identification, mapping, and basic filtering are stored. These include an internal id, google_place_id, name, latitude, longitude, address, price_level, and business_status. Google-provided ratings and rating counts are intentionally excluded because they do not align with the project’s contextual rating model and add no value to downstream logic. A theoretical user could find this information elsewhere if necessary; the app should not need to provide it.

## User Context and Organization Model
The primary abstraction in the system is the user-defined list. Lists function similarly to playlists in Spotify. A list represents a context in which restaurants are meaningfully comparable. Examples include cuisine-based groupings, price-based groupings, geographic groupings, or occasion-based groupings. Users may create any number of lists, name them freely, and add or remove restaurants at will. Restaurants may belong to multiple lists simultaneously. The system does not impose a predefined taxonomy or hierarchy.

For MVP purposes, lists may also be created implicitly by the system in response to a user’s answers to a guided questionnaire (e.g., “Chinese or Japanese, within 3km, under $30”), and named automatically for traceability.

## Ratings Model
Ratings are defined as a relationship between a user, a restaurant, and a list. There is no concept of a global restaurant rating. A restaurant may have multiple ratings by the same user, as long as they occur in different lists. This ensures ratings are always contextual and semantically coherent. Ratings use a fixed 1–5 integer scale and are meaningful only within the list in which they are given. The user interface (even if minimal) should present restaurants within the same context during rating to encourage relative judgment.

## ML-based Recommendation System
The system will support an explicit recommendation action initiated by the user through a guided questionnaire. The user answers a small number of discrete questions (e.g., cuisine preference, maximum distance, price sensitivity) to define a context. The recommendation engine selects candidate restaurants matching these constraints and produces a predicted preference score. The system then recommends an adjustable number (e.g., three) of options. More options means less questions required.

Crucially, every recommendation is followed by explicit user feedback when the user visits and rates the restaurant within the inferred or selected context. The system records both the predicted score and the actual rating.

This functionality is currently deferred but enabled by design. Because ratings are contextual, labeled, and explicit, the resulting dataset is significantly cleaner than typical restaurant recommendation data. Features may include list context, price level, distance, and user history within similar lists.

A simple baseline (e.g., average rating in context) will be used initially; a lightweight regressor (e.g., linear model) may follow. Cold-start recommendations may temporarily leverage Google’s ratings but are flagged and excluded from training data. Every recommendation includes a traceable reason field (e.g., "cold_start" or "ml_prediction") to support future evaluation.

## Schema Evolution and Extensibility
The schema is designed to evolve without requiring additional Google API calls. Optional raw Google Places responses may be stored to allow future feature extraction. User-defined lists naturally support further subdivision without schema changes. Additional metadata or embeddings can be added later without invalidating existing data.

The core tables—restaurants, lists, list_restaurants, ratings, and recommendations—are normalized to support correct relational semantics while allowing JSON-encoded fields for MVP simplicity in non-critical paths (e.g., list_ids in recommendations).

## Concluding Thoughts & Future Directions
The design implements contextual, user-defined comparisons that scale naturally with user history and do not lose relevance. The system is intentionally simple, modular, and aligned with user behavior, addressing a concrete usability flaw in existing applications while remaining extensible. It is intentionally lacking elements that would make it a complete product. This project was created with a short timeline in mind(<2 weeks). I wanted to test my software engineering knowledge and my ability to shape ideas into logic to create a functional proof of concept. I am currently not well-versed in system design, frontend, or UI/UX so a great deal of time was spent designing, debugging, and learning what was required via AI coding assistance.

<details>
<summary>Future directions</summary>
The creation of a simple mobile app to host the project instead of hosting it locally. 

The implementation of a very basic social features just to allow adding people you know and being able to look at lists that they have publicly available(similar to Spotify). This project avoided designing a social media platform the way Beli seems to be developing. I think people might have mixed opinions about this but some users might not really care what other people think. Individual palates are very different. As it stands, sharing lists with other users and adding more restaurants is possible but user unfriendly. You could share personal databases with other users or modify the code directly to poll the Google Places API using your own API key and obtain more locations.


The implementation of a basic interactive map and integrating simple geospatial analysis into the machine learning components. I imagine that this would be very involved and require a complete rehauling of the current data sourcing. 

The current data sourcing method is a huge source of potential improvements. The query nearby radius was originally 600m but the Google Places API can only return 20 queries at a time meaning I would occasionally lose restaurants in extremely dense locations such as Mission, San Francisco. I had to bring it down as low as 100m to guarantee I did not miss locations. I am also limited by Google Cloud free use limits that only allow the API to be polled 5000 times/month as well as my lack of knowledge with the API. I am almost certain there can be a more efficient implementation and it would be almost required to scale this app beyond its current limitations. 

The database implementation is also inherently problematic for scalability even if currently acceptable given the scope. It would eventually need to be imported to something like PostgreSQL and the underlying backend would need to move away from its current monolithic design towards something like microservices.

Substantial optimizations and improvements to the machine learning aspects. I don't have industry experience designing systems that scale to millions of users nor handling such data. The testing of the recommendation features was difficult and likely subject to my own biases. It's possible others might see it as unusable. The inspiration behind the questionnaire feature was Akinator.

Priorities(Hopefully)
Engineering rigor > breadth of features --> clean and functional backend and ML pipeline design.
</details>

If you made it this far; how'd I do?

