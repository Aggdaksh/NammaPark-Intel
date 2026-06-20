# NammaPark Intel 🚔🚙

**Transforming Raw Traffic Citations into Geospatial Intelligence.**

NammaPark Intel is an AI-powered geospatial intelligence platform designed for the Bengaluru Traffic Police. It ingests raw parking violation data and uses advanced Machine Learning to predict congestion hotspots, optimize patrol routes, and provide an Explainable AI Commander for dispatchers.

---

## 🏆 Key Features for Hackathon Judges

1. **True Delay Modeling (Not just heatmaps)**
   Instead of simple density maps, we mathematically model the actual congestion delay caused by parked vehicles using a modified **Bureau of Public Roads (BPR)** function, factoring in road capacity, lane count, and severity.
2. **Machine Learning & Anomaly Detection**
   Uses **LightGBM** (DART) to predict cluster risk and Scikit-Learn's **Isolation Forest** to automatically flag massive temporal spikes in violations ($>3\sigma$ above baseline).
3. **Advanced 3D Geospatial Rendering**
   Built with **Deck.gl** and the **H3 Hexagonal Spatial Index** (created by Uber) over a completely free **CARTO Dark Matter** base map. 
4. **Operations Research (VRP)**
   Uses **Google OR-Tools** to solve the Capacitated Vehicle Routing Problem, automatically generating the most optimal patrol routes from police stations to high-risk clusters.
5. **Grounded AI Commander (Google Gemini)**
   Integrated with **Gemini 2.5 Flash**. To prevent AI hallucinations, we use **TreeSHAP** to extract the exact mathematical drivers of our ML model (e.g., *"+12.4 mins due to high junction proximity"*), and securely inject them into Gemini's context window via RAG. The AI explains *exactly* why the model flagged an area.

---

## 🛠️ Technology Stack

### Frontend
- **Next.js (App Router)** & **React**
- **TailwindCSS**
- **Deck.gl** (WebGL-powered 3D Map rendering)
- **Recharts** (Data Visualization)
- **Deployed on Vercel**

### Backend & ML
- **FastAPI** (High-performance Async Python API)
- **Google GenAI SDK** (Gemini 2.5 Flash)
- **LightGBM, SHAP, Scikit-Learn**
- **GeoPandas, OSMnx, H3** (Spatial processing)
- **OR-Tools** (Routing solver)
- **PostgreSQL + PostGIS** (Neon) & **Redis** (Upstash)
- **Deployed on Render / Railway**

---

## 🚀 How to Run Locally

NammaPark Intel uses a **Tiered Fallback Architecture**. If you don't have the databases configured, the backend gracefully falls back to local pre-computed ML artifacts, meaning **you can run the entire app locally with almost zero setup.**

### 1. Start the FastAPI Backend
```bash
# Optional: Set your Gemini Key to enable the AI Commander
export GEMINI_API_KEY="your_api_key_here"

# Install dependencies
pip install .

# Run the API
uvicorn api.main:app --reload --port 8000
```
*The API will be available at `http://localhost:8000/docs`.*

### 2. Start the Next.js Frontend
Open a new terminal window:
```bash
cd frontend

# Install UI dependencies
npm install

# Run the development server
npm run dev
```
*The dashboard and 3D map will be live at `http://localhost:3000`.*

---

## 🏗️ Architecture & Documentation

For judges looking to understand the deep technical decisions, mathematical formulas, and the full data flow pipeline, please review our comprehensive architecture document:

👉 [**View the Comprehensive Technical Architecture Document**](docs/nammapark_intel_architecture.md)

---

## 📡 API Contract Overview
- `POST /api/ingest` - Accepts raw CSV uploads for processing.
- `GET /api/hotspots` - Returns H3 clusters ranked by BPR delay.
- `GET /api/patrol-routes` - Returns OR-Tools optimized GeoJSON paths.
- `GET /api/anomalies` - Returns active Isolation Forest exception alerts.
- `POST /api/commander` - Conversational endpoint powered by Gemini and SHAP.
