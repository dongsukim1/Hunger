const API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`;

let restaurantId = null;

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

// --- Event Listeners ---
document.addEventListener('DOMContentLoaded', () => {
  renderLists();
  document.getElementById('restaurantSearch').addEventListener('input', searchRestaurants);
});
