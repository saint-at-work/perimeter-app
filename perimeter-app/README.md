# Perimeter — Geofenced Attendance Console

## Project structure
```
perimeter-app/
  backend/          FastAPI + SQLite — the real point-in-polygon & dwell-time logic
    main.py         API routes
    models.py       DB tables (Event, CheckIn, AttendanceRecord)
    schemas.py      request/response shapes
    geo.py          point-in-polygon math
    database.py     SQLite engine setup
    requirements.txt
  frontend/         Plain HTML/JS — no build step needed
    index.html
    app.js
    styles.css
```

## Open in VS Code
1. Unzip this folder, then in VS Code: **File → Open Folder** → select `perimeter-app`.
2. You should see `backend/` and `frontend/` in the file explorer.

## Run the backend
In a VS Code terminal (`` Ctrl+` ``):
```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```
This starts the API at `http://localhost:8000`. A `perimeter.db` SQLite file is created automatically on first run. You can browse the auto-generated API docs at `http://localhost:8000/docs`.

## Run the frontend
Geolocation requires either `https://` or `localhost` — opening `index.html` directly via `file://` will block it in most browsers. Serve it locally instead, in a **second terminal**:
```bash
cd frontend
python -m http.server 5500
```
Then open `http://localhost:5500` in your browser (ideally on your phone, on the same Wi-Fi — see note below).

## Using it
**Organizer tab:** walk the venue boundary, tap "Drop Marker Here" at each corner, close the polygon, set the confirmation threshold, tap "Create Event" — note the Event ID it returns.

**Attendee tab:** enter that Event ID and a name/ID, tap "Start Check-In" — it'll ping the backend every time your GPS updates, and confirm attendance once you've stayed inside the boundary past the threshold.

## Testing on your actual phone
Your phone needs to reach the backend, so `localhost` won't work from a phone unless it's the same device:
1. Find your computer's local IP (e.g. `192.168.1.42`) — `ipconfig` (Windows) or `ifconfig`/`ipconfig getifaddr en0` (Mac).
2. Run backend with `uvicorn main:app --reload --host 0.0.0.0`.
3. On the frontend, set the "Backend" field to `http://192.168.1.42:8000` (both tabs).
4. Serve frontend with `python -m http.server 5500 --bind 0.0.0.0`, then visit `http://192.168.1.42:5500` from your phone.
5. Phone and computer must be on the same Wi-Fi network. Most mobile browsers also require HTTPS for geolocation outside of localhost — if it's blocked, look into a free tunnel like `ngrok` to get an HTTPS URL during testing.

## What's real vs. what's a placeholder
- **Real:** point-in-polygon math, server-side dwell tracking (so it can't be faked by editing frontend JS), SQLite persistence, REST API.
- **Placeholder for a real deployment:** no authentication (`user_id` is just a free-text string — anyone can type any name), CORS wide open, SQLite instead of Postgres, no HTTPS. Fine for a prototype/demo; all worth hardening before real use.
