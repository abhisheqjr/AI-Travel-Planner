VoyageAgent: Agentic AI Travel Planner

VoyageAgent is a high-fidelity, premium AI-powered travel planner that creates complete, personalized travel itineraries in real-time. By leveraging **LangGraph** agentic workflows, **Groq (Llama 3)**, **Supabase**, and live web searching via **SerpAPI**, VoyageAgent pulls real flight options, accommodation listings, local dining spots, and must-visit attractions to assemble an hour-by-hour visual dashboard and a downloadable PDF plan.

---

## Features

- **Conversational Agentic AI:** Chat-based interface powered by LangGraph & Groq (`llama-3.3-70b-versatile`) that dynamically gathers your destination, budget, trip duration, and specific interests.
- **Agent Memory & Dual-Layer Context:** Incorporates a sliding conversation window buffer (retaining the last 20 messages for immediate context) alongside a background summarization by llm for chats in history(which saves a dense 50-word summary in Supabase and injects it into subsequent session prompts for long-term memory without token overflow).
- **Real-Time Search & Feasibility Engine:** Uses SerpAPI to query live APIs and Google Search for:
- **Transport & Route Feasibility:** Resolves IATA codes and validates flights, rail, and road accessibility between cities.
- **Hotel & Accommodation:** Fetches real prices, star ratings, amenities, reviews, and thumbnail images.
- **Famous Food & Dining:** Identifies top-rated restaurants, cuisines, and signature dishes.
- **Top Spots to Visit:** Highlights main local attractions, activities, and entry fees.
- **Detailed Day-by-Day Timelines:** Synthesizes structured hour-by-hour schedules covering morning, lunch, afternoon, dinner, and evening plans.
- **Downloadable PDF Itineraries:** Instantly generates a clean, styled, print-ready PDF document of your entire trip using ReportLab.
- **Secure Account Portal:** Supabase integration featuring OTP email verification via SMTP, secure profiles, saved travel dashboards, and profile/password modification workflows.

---

## Technology Stack

- **Backend:** Flask (Python), Python-Dotenv
- **AI Agentic Layer:** LangGraph, LangChain Core, Pydantic, Groq Cloud API
- **Data & APIs:** SerpAPI (Google Flights, Google Hotels, Google Maps), Supabase (PostgreSQL & Auth client)
- **PDF Generation:** ReportLab
- **Frontend:** Vanilla CSS3 (Custom design system), HTML5, Vanilla JavaScript

---


### Prerequisites
- Python 3.10+
- A Supabase account (for database schema & auth)
- API Keys for:
  - Groq Console
  - SerpAPI

###  Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/voyageagent.git
   cd voyageagent
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in the root folder and add the following keys:
   ```ini
   GROQ_API_KEY=your_groq_api_key_here
   SERPAPI_API_KEY=your_serpapi_key_here
   SUPABASE_URL=your_supabase_project_url_here
   SUPABASE_KEY=your_supabase_anon_key_here
   ```

4. **Initialize Database:**
   Import the database schema in `supabase_schema.sql` into your Supabase SQL Editor to configure tables for users, sessions, and saved itineraries.

5. **Run the Server:**
   ```bash
   python app.py
   ```
   Open your browser and navigate to `http://127.0.0.1:5000` to start planning!

## Deployment

This project is deployed using Vercel. Use the below link to access:
- [VoyageAgent Live App](https://ai-travel-planner-rouge-nine.vercel.app/)