/**
 * ThermaPulse EV Cockpit - Client Configuration
 * ==============================================================================
 * For static deployment (e.g., Vercel, Netlify, GitHub Pages):
 * Set BACKEND_URL to the public URL of your containerized FastAPI server
 * (e.g., "https://thermapulse-ev-backend.onrender.com" or "https://aura-ev.up.railway.app").
 *
 * If left empty (""), the client automatically connects to the current host origin,
 * or http://localhost:8000 when running locally.
 *
 * You can also change the backend URL interactively at runtime in the Cockpit UI!
 * ==============================================================================
 */
window.AURA_CONFIG = {
  BACKEND_URL: "" // Example: "https://aura-ev-dashboard.onrender.com"
};
