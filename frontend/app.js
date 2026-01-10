const API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`;

let restaurantId = null;
let recommendSession = null; // { sessionId, maxQuestions, minCandidates }
let addressDebounceTimer = null;
const MAPBOX_PUBLIC_TOKEN = "pk.eyJ1IjoiYXNkYXNkYS1hc2Rhc2RhIiwiYSI6ImNtazV5ZnIzZTBvZnozZnExOXFtOXNmeGwifQ.ksZ3_paAz6QE6uhh5fsDnw"; // Public token for geocoding/autocomplete with all fine-grained permissions disabled. No vulnerabilities. URL restrictions in place so only works on local dev envs.
// THIS IS SAFE TO EXPOSE PUBLICLY AS IT HAS ALL EXPLOITABLE PERMISSIONS DISABLED AND URL RESTRICTIONS SET UP IN MAPBOX DASHBOARD.

// Mission SF bounding box (same as backend)
const MISSION_SF_BBOX = {
  minLat: 37.74802895624222,
  maxLat: 37.769249996806195,
  minLng: -122.42248265700066,
  maxLng: -122.40801467343661
};

// --- List Creation ---
async function createList() {
  const name = document.getElementById('listName').value.trim();
  if (!name) {
    alert('Please enter a list name');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/lists`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    const data = await res.json();
    if (res.ok) {
      document.getElementById('listResult').innerHTML = `✅ List created: "${data.name}"`;
      document.getElementById('listName').value = '';
      renderLists(); // update sidebar
    } else {
      document.getElementById('listResult').innerHTML = `❌ Error: ${JSON.stringify(data)}`;
    }
  } catch (e) {
    document.getElementById('listResult').innerHTML = `❌ Network error: ${e.message}`;
  }
}

// --- Load Lists for Dropdown ---
async function loadLists() {
  try {
    const res = await fetch(`${API_BASE}/lists`);
    const lists = await res.json();
    const select = document.getElementById('listSelect');
    select.innerHTML = '<option value="">-- Select a list --</option>';
    lists.forEach(list => {
      const opt = document.createElement('option');
      opt.value = list.id;
      opt.textContent = list.name;
      select.appendChild(opt);
    });
    select.disabled = false;
  } catch (e) {
    alert('Failed to load lists');
  }
}

// --- Restaurant Search ---
async function searchRestaurants() {
  const query = document.getElementById('restaurantSearch').value;
  const suggestionsDiv = document.getElementById('restaurantSuggestions');
  
  if (query.length < 2) {
    suggestionsDiv.style.display = 'none';
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/restaurants/search?q=${encodeURIComponent(query)}`);
    const results = await res.json();
    
    suggestionsDiv.innerHTML = '';
    results.forEach(r => {
      const el = document.createElement('div');
      el.textContent = r.name;
      el.style.padding = '0.4rem';
      el.style.cursor = 'pointer';
      el.style.borderBottom = '1px solid #f0f0f0';
      el.addEventListener('click', () => {
        restaurantId = r.id;
        document.getElementById('restaurantSearch').value = r.name;
        suggestionsDiv.style.display = 'none';
      });
      el.addEventListener('mouseover', () => el.style.background = '#f0f8ff');
      el.addEventListener('mouseout', () => el.style.background = '');
      suggestionsDiv.appendChild(el);
    });
    
    suggestionsDiv.style.display = results.length ? 'block' : 'none';
  } catch (e) {
    console.error(e);
    suggestionsDiv.style.display = 'none';
  }
}

// --- Submit Rating ---
async function rateRestaurantByName() {
  const listId = document.getElementById('listSelect').value;
  const rating = document.getElementById('rating').value;
  
  if (!restaurantId || !listId || !rating) {
    alert('Please select a restaurant, list, and rating');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/rate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        restaurant_id: restaurantId, 
        list_id: parseInt(listId), 
        rating: parseInt(rating) 
      })
    });
    const data = await res.json();
    document.getElementById('rateResult').innerHTML = 
      res.ok ? '✅ Rating submitted!' : `❌ Error: ${JSON.stringify(data)}`;
  } catch (e) {
    document.getElementById('rateResult').innerHTML = `❌ Network error: ${e.message}`;
  }
}

// Shared function to fetch lists
async function fetchLists() {
  const res = await fetch(`${API_BASE}/lists`);
  if (!res.ok) throw new Error("Failed to fetch lists");
  return await res.json();
}

// Auto-purge deleted lists older than 30 days
async function purgeOldDeletedLists() {
  try {
    await fetch(`${API_BASE}/lists/deleted/purge`, { method: 'POST' });
  } catch (e) {
    console.warn("Failed to purge old deleted lists:", e);
  }
}

async function renderLists() {
  try {
    // Auto-purge old deleted lists
    await fetch(`${API_BASE}/lists/deleted/purge`, { method: 'POST' });

    // Fetch active lists
    const activeRes = await fetch(`${API_BASE}/lists`);
    const activeLists = await activeRes.json();

    // Fetch deleted lists
    const deletedRes = await fetch(`${API_BASE}/lists/deleted`);
    const deletedLists = await deletedRes.json();

    // Render active lists (sidebar)
    const container = document.getElementById('listsContainer');
    let html = '';

    if (activeLists.length > 0) {
      html += '<h4>Active Contexts</h4>';
      html += activeLists.map(list => `
        <div style="padding:0.5rem; border-bottom:1px solid #eee; display:flex; justify-content:space-between;">
          <span>${list.name}</span>
          <button onclick="softDeleteList(${list.id})" style="color:red; background:none; border:none; cursor:pointer;">🗑️</button>
        </div>
      `).join('');
    }

    // Render deleted lists (with undo)
    if (deletedLists.length > 0) {
      html += '<h4 style="margin-top:1rem;">Recently Deleted <small>(auto-removed after 30 days)</small></h4>';
      html += deletedLists.map(list => `
        <div style="padding:0.5rem; border-bottom:1px solid #f8d7da; background:#f8d7da; display:flex; justify-content:space-between;">
          <span style="color:#721c24;">${list.name}</span>
          <button onclick="restoreList(${list.id})" style="color:#155724; background:none; border:none; cursor:pointer; font-weight:bold;">↩️ Undo</button>
        </div>
      `).join('');
    }

    if (!activeLists.length && !deletedLists.length) {
      html = '<em>No lists yet</em>';
    }

    container.innerHTML = html;

    // Update dropdown
    const select = document.getElementById('listSelect');
    select.innerHTML = '<option value="">-- Select a list --</option>';
    activeLists.forEach(list => {
      const opt = document.createElement('option');
      opt.value = list.id;
      opt.textContent = list.name;
      select.appendChild(opt);
    });

  } catch (e) {
    console.error("Failed to load lists:", e);
    document.getElementById('listsContainer').innerHTML = '<em>Failed to load</em>';
  }
}

async function deleteList(listId) {
  if (!confirm("Delete this list? Ratings will be kept but hidden.")) return;
  
  try {
    const res = await fetch(`${API_BASE}/lists/${listId}`, { method: 'DELETE' });
    if (res.ok) {
      renderLists();
    } else {
      alert("Failed to delete list");
    }
  } catch (e) {
    alert("Network error");
  }
}

async function softDeleteList(listId) {
  if (!confirm("Delete this list? You can undo this for 30 days.")) return;
  
  try {
    const res = await fetch(`${API_BASE}/lists/${listId}`, { method: 'DELETE' });
    if (res.ok) {
      renderLists(); // refresh UI
    } else {
      alert("Failed to delete list");
    }
  } catch (e) {
    alert("Network error");
  }
}

async function restoreList(listId) {
  try {
    const res = await fetch(`${API_BASE}/lists/${listId}/restore`, { method: 'POST' });
    if (res.ok) {
      renderLists(); // refresh UI
    } else {
      alert("Failed to restore list");
    }
  } catch (e) {
    alert("Network error");
  }
}

// Recommendation Flow 1/6/2026

function isInMissionSF(lat, lng) {
  return lat >= MISSION_SF_BBOX.minLat && lat <= MISSION_SF_BBOX.maxLat &&
         lng >= MISSION_SF_BBOX.minLng && lng <= MISSION_SF_BBOX.maxLng;
}

// Geocoding helper using Mapbox temporary geocoding with browser built-in as fallback
async function geocodeAddress(address) {
  if (!address.trim()) {
    throw new Error("Address is empty");
  }
  
  try {
    const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(address)}.json?access_token=${MAPBOX_PUBLIC_TOKEN}&types=address,poi&limit=1`;
    
    const response = await fetch(url);
    const data = await response.json();
    
    if (!response.ok) {
      console.error("Mapbox error:", data);
      throw new Error(`Geocoding failed: ${data.message || 'Unknown error'}`);
    }
    
    if (!data.features || data.features.length === 0) {
      throw new Error("No results found for that address");
    }
    
    const feature = data.features[0];
    const [lng, lat] = feature.center; // Mapbox returns [longitude, latitude]
    
    return { 
      latitude: lat, 
      longitude: lng, 
      placeName: feature.place_name 
    };
  } catch (error) {
    console.error("Geocoding error:", error);
    throw new Error(`Geocoding failed: ${error.message}`);
  }
}

// Show modal with content
async function showRecommendModal(html) {
  document.getElementById('recommendContent').innerHTML = html;
  document.getElementById('recommendModal').style.display = 'flex';
}

// Close modal
async function closeRecommendModal() {
  document.getElementById('recommendModal').style.display = 'none';
  recommendSession = null;
}

// Start the flow
async function startRecommendationFlow() {
  const html = `
    <h3>Where are you?</h3>
    <p style="font-size:0.9rem; color:#666;">Demo limited to Mission District, San Francisco</p>
    
    <div style="margin:1rem 0; position: relative;">
      <input type="text" id="addressInput" 
       placeholder="e.g., 24th St & Valencia, SF" 
       style="width:100%;" 
       oninput="handleAddressInput()" />
      <div id="addressSuggestions" style="
        position: absolute;
        z-index: 1001;
        background: white;
        border: 1px solid #ccc;
        border-top: none;
        max-height: 150px;
        overflow-y: auto;
        width: 100%;
        box-shadow: 0 2px 6px rgba(0,0,0,0.15);
        display: none;
      "></div>
    </div>

    <button onclick="useCurrentLocation()" style="background:#28a745; margin: 0.5rem 0;">Use Current Location</button>
    
    <div style="margin:1rem 0;">
      <label>Max distance: <span id="distanceValue">3</span> miles</label><br>
      <input type="range" id="distanceSlider" min="1" max="5" value="3.0" 
             oninput="document.getElementById('distanceValue').textContent = this.value" />
    </div>
    
    <div style="margin-top:1.5rem;">
      <button onclick="submitLocation()" style="background:#28a745;">Start</button>
      <button onclick="closeRecommendModal()" style="background:#6c757d; margin-left:0.5rem;">Cancel</button>
    </div>
    <div id="locationError" style="color:red; margin-top:0.5rem; min-height:1.2rem;"></div>
  `;
  showRecommendModal(html);
}

// Geolocation
async function useCurrentLocation() {
  const errorEl = document.getElementById('locationError');
  errorEl.textContent = "";

  if (!navigator.geolocation) {
    errorEl.textContent = "Geolocation not supported.";
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (position) => {
      const { latitude, longitude } = position.coords;
      if (!isInMissionSF(latitude, longitude)) {
        errorEl.textContent = "You're outside the demo area (Mission District). Please move or enter an address nearby.";
        return;
      }
      // Auto-fill for transparency
      document.getElementById('addressInput').value = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
      startRecommendationSession(latitude, longitude);
    },
    (error) => {
      console.error("Geolocation error:", error);
      errorEl.textContent = "Failed to get location. Please enter an address.";
    }
  );
}

// Submit location (from address or coords)
async function submitLocation() {
  const input = document.getElementById('addressInput').value.trim();
  const distance = parseFloat(document.getElementById('distanceSlider').value) || 3.0;
  const errorEl = document.getElementById('locationError');
  errorEl.textContent = ""; // clear previous error

  if (!input) {
    errorEl.textContent = "Please enter a location.";
    return;
  }

  // 1. Check if input has shape of lat/long coordinates i.e "37.7550, -122.4150"
  const coordMatch = input.match(/^(-?\d+\.\d+),\s*(-?\d+\.\d+)$/);
  if (coordMatch) {
    const lat = parseFloat(coordMatch[1]);
    const lng = parseFloat(coordMatch[2]);
    if (!isInMissionSF(lat, lng)) {
      errorEl.textContent = "Coordinates outside Mission District.";
      return;
    }
    startRecommendationSession(lat, lng, distance);
    return;
  }

  // 2. Treat as address → geocode with Mapbox (temporary geocoding)
  try {
    const { latitude, longitude, placeName } = await geocodeAddress(input);
    
    // update input to show resolved address
    document.getElementById('addressInput').value = placeName;

    if (!isInMissionSF(latitude, longitude)) {
      errorEl.textContent = "Address is outside the demo area (Mission District). Try: '24th & Valencia, SF'";
      return;
    }

    startRecommendationSession(latitude, longitude, distance);
  } catch (e) {
    errorEl.textContent = `Geocoding failed: ${e.message}`;
  }
}

// Start session with backend
async function startRecommendationSession(lat, lng, maxDistanceMiles = 3.0) {
  try {
    const res = await fetch(`${API_BASE}/recommend/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        user_latitude: lat, 
        user_longitude: lng, 
        max_distance_miles: maxDistanceMiles,
        max_questions: 5  // default; will become configurable later
      })
    });
    
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to start session");
    }
    
    const data = await res.json();
    recommendSession = { 
      sessionId: data.session_id,
      maxQuestions: 5,
      minCandidates: 3
    };
    
    showQuestion(data.question, data.candidates_count);
  } catch (e) {
    document.getElementById('locationError').textContent = `Error: ${e.message}`;
  }
}

// Show a question
function showQuestion(question, count) {
  const optionsHtml = question.options.map(opt => 
    `<button onclick="submitAnswer('${opt}')" style="margin:0.25rem;">${opt}</button>`
  ).join('');
  
  const html = `
    <h3>${question.text}</h3>
    <p style="font-size:0.9rem; color:#666;">${count} options remaining</p>
    <div style="margin:1.5rem 0;">${optionsHtml}</div>
    <button onclick="closeRecommendModal()" style="background:#6c757d;">Cancel</button>
    <div id="answerError" style="color:red; margin-top:0.5rem; min-height:1.2rem;"></div>
  `;
  showRecommendModal(html);
}

// Submit answer
async function submitAnswer(answer) {
  if (!recommendSession) return;
  
  try {
    const res = await fetch(`${API_BASE}/recommend/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        session_id: recommendSession.sessionId,
        answer: answer
      })
    });
    
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to process answer");
    }
    
    const data = await res.json();
    
    // Check if complete
    if (data.recommendations) {
      showRecommendations(data.recommendations);
    } else if (data.question) {
      showQuestion(data.question, data.candidates_count);
    } else {
      throw new Error("Unexpected response");
    }
  } catch (e) {
    document.getElementById('answerError').textContent = `Error: ${e.message}`;
  }
}

// Show final recommendations
function showRecommendations(recs) {
  const recsHtml = recs.map(r => `
    <div style="padding:0.75rem; border-bottom:1px solid #eee;">
      <strong>${r.name}</strong><br>
      <span style="color:#666;">${r.cuisine} • ${'$'.repeat(r.price_tier)} • ${r.distance_miles} miles</span>
    </div>
  `).join('');
  
  const html = `
    <h3>We found your match!</h3>
    ${recsHtml}
    <div style="margin-top:1.5rem;">
      <button onclick="closeRecommendModal()" style="background:#28a745;">Done</button>
      <!-- Future: add feedback UI here -->
    </div>
  `;
  showRecommendModal(html);
}

async function handleAddressInput() {
  const input = document.getElementById('addressInput');
  const query = input.value.trim();
  const suggestionsDiv = document.getElementById('addressSuggestions');
  
  // Clear suggestions if query too short
  if (query.length < 3) {
    suggestionsDiv.style.display = 'none';
    return;
  }

  // Debounce: wait 750ms after user stops typing
  if (addressDebounceTimer) clearTimeout(addressDebounceTimer);
  addressDebounceTimer = setTimeout(async () => {
    try { 
      // Mapbox autocomplete endpoint
      const url = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(query)}.json?` + 
                  `access_token=${MAPBOX_PUBLIC_TOKEN}&autocomplete=true&country=US&types=address,poi&limit=5`;
      
      const response = await fetch(url);
      const data = await response.json();
      
      // Clear and hide if no results
      suggestionsDiv.innerHTML = '';
      if (!data.features || data.features.length === 0) {
        suggestionsDiv.style.display = 'none';
        return;
      }
      
      // Render suggestions
      data.features.forEach(feature => {
        const el = document.createElement('div');
        el.textContent = feature.place_name;
        
        el.addEventListener('click', () => {
          input.value = feature.place_name;     // fill input
          suggestionsDiv.style.display = 'none'; // hide
        });
        
        el.addEventListener('mouseover', () => el.style.background = '#f0f8ff');
        el.addEventListener('mouseout', () => el.style.background = '');
        
        suggestionsDiv.appendChild(el);
      });
      
      suggestionsDiv.style.display = 'block';
    } catch (error) {
      console.error("Autocomplete error:", error);
      suggestionsDiv.style.display = 'none';
    }
  }, 750); // 750ms debounce. Intentionally very slow to reduce API calls. I only get a 1000/month for free ):
}

// --- Event Listeners ---
document.addEventListener('DOMContentLoaded', () => {
  renderLists();
  document.getElementById('restaurantSearch').addEventListener('input', searchRestaurants);
  
  // Recommendation flow button
  const recommendButton = document.getElementById('startRecommendation');
  if (recommendButton) {
    recommendButton.addEventListener('click', startRecommendationFlow);
  }
});