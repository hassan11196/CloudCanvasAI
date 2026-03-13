# Zephior Canvas Frontend

Vite + React frontend for Zephior Canvas.

## Setup

1. Install dependencies:
   ```bash
   npm install
   ```

2. Configure environment variables:
   ```bash
   cp .env.example .env
   ```

   Update `.env` with your Firebase web config:
   - `VITE_FIREBASE_API_KEY`
   - `VITE_FIREBASE_AUTH_DOMAIN`
   - `VITE_FIREBASE_PROJECT_ID`
   - `VITE_FIREBASE_APP_ID`
   - `VITE_FIREBASE_MESSAGING_SENDER_ID`

3. Run the development server:
   ```bash
   npm run dev
   ```

The app runs at `http://localhost:5173` by default.
