from fastapi import FastAPI, Depends, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from common.config import settings
from api.router import router

from common.repository import WatchRulesRepository, TripSnapshotRepository, NotificationHistoryRepository, AppConfigRepository, AlertCacheRepository
from common.utils import POPULAR_STATIONS
from common.redis_client import get_redis_client
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="TCDD Ticket Watcher", version="1.0.0")
templates = Jinja2Templates(directory="api/templates")

# Add CORS middleware for better API compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }
    
    # Check database
    try:
        with Session(engine) as session:
            session.exec(select(WatchRule).limit(1)).first()
        health["components"]["database"] = "connected"
    except Exception as e:
        health["components"]["database"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    # Check Redis
    try:
        redis = get_redis_client()
        redis.ping()
        health["components"]["redis"] = "connected"
    except Exception as e:
        health["components"]["redis"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    return health

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page - protected by auth middleware."""
    try:
        with Session(engine) as session:
            # Fetch recent snapshots for initial render (optional, since JS will poll)
            snapshots = session.exec(
                select(TripSnapshot)
                .order_by(desc(TripSnapshot.last_seen_at))
                .limit(50)
            ).all()
            
            # Enrich with rule info
            data = []
            for snap in snapshots:
                rule = session.get(WatchRule, snap.rule_id)
                data.append({
                    "date": snap.trip_date,
                    "route": f"{rule.from_station} -> {rule.to_station}" if rule else "Unknown",
                    "time": snap.dep_time,
                    "arr_time": getattr(snap, 'arr_time', '23:59'),
                    "train": snap.train_name,
                    "seats": snap.seats_available,
                    "price": snap.price,
                    "seen": snap.last_seen_at.strftime("%H:%M:%S")
                })
                
        return templates.TemplateResponse(
            "dashboard.html", 
            {
                "request": request, 
                "matches": data, 
                "stations": POPULAR_STATIONS,
                "default_chat_id": settings.TELEGRAM_CHAT_ID or ""
            }
        )
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "matches": [],
                "stations": POPULAR_STATIONS,
                "default_chat_id": settings.TELEGRAM_CHAT_ID or ""
            }
        )
@app.get("/api/stats", response_class=JSONResponse)
async def api_stats(request: Request):
    """Get current stats: active watchers and found tickets."""
    try:
        with Session(engine) as session:
            # Fetch active rules
            rules = session.exec(
                select(WatchRule)
                .where(WatchRule.enabled == True)
                .order_by(desc(WatchRule.created_at))
            ).all()
            
            rules_data = [{
                "id": str(r.id),
                "route": f"{r.from_station} -> {r.to_station}",
                "date": r.date_start,
                "ticket_type": r.ticket_type,
                "chat_id": r.chat_id,
                "after_time": r.after_time,
                "before_time": r.before_time,
                "enabled": r.enabled
            } for r in rules]

            # Fetch recent snapshots
            snapshots = session.exec(
                select(TripSnapshot)
                .order_by(desc(TripSnapshot.last_seen_at))
                .limit(100)  # Increased limit for better UX
            ).all()
            
            matches_data = []
            for snap in snapshots:
                rule = session.get(WatchRule, snap.rule_id)
                matches_data.append({
                    "id": str(snap.id),
                    "rule_id": str(snap.rule_id) if snap.rule_id else None,
                    "date": snap.trip_date,
                    "route": f"{rule.from_station} -> {rule.to_station}" if rule else "Unknown",
                    "time": snap.dep_time,
                    "arr_time": getattr(snap, 'arr_time', '23:59'),
                    "train": snap.train_name or "TCDD Train",
                    "seats": snap.seats_available or 0,
                    "price": float(snap.price) if snap.price else 0.0,
                    "economy_seats": snap.economy_seats or 0,
                    "economy_price": float(snap.economy_price) if snap.economy_price else 0.0,
                    "business_seats": snap.business_seats or 0,
                    "business_price": float(snap.business_price) if snap.business_price else 0.0,
                    "loca_seats": snap.loca_seats or 0,
                    "loca_price": float(snap.loca_price) if snap.loca_price else 0.0,
                    "seen": snap.last_seen_at.strftime("%H:%M:%S") if snap.last_seen_at else ""
                })
                
        return JSONResponse({
            "rules": rules_data,
            "matches": matches_data,
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

@app.post("/rules", response_class=RedirectResponse)
async def create_rule(
    request: Request,
    from_station: str = Form(...),
    to_station: str = Form(...),
    date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    ticket_type: str = Form("regular"),
    chat_id: int = Form(...),
):
    """Create a new watcher rule."""
    # Validate inputs
    if not from_station or not to_station:
        raise HTTPException(status_code=400, detail="From and To stations are required")
    
    if from_station == to_station:
        raise HTTPException(status_code=400, detail="From and To stations must be different")
    
    if not date:
        raise HTTPException(status_code=400, detail="Date is required")
    
    # Validate time format
    try:
        start_hour, start_min = map(int, start_time.split(":"))
        end_hour, end_min = map(int, end_time.split(":"))
        if not (0 <= start_hour < 24 and 0 <= start_min < 60):
            raise ValueError("Invalid start time")
        if not (0 <= end_hour < 24 and 0 <= end_min < 60):
            raise ValueError("Invalid end time")
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid time format")
    
    if chat_id <= 0:
        raise HTTPException(status_code=400, detail="Valid Telegram Chat ID is required")
    
    # Normalize Date: Browser sends YYYY-MM-DD, Scraper needs DD.MM.YYYY
    final_date = date
    if "-" in date:
        try:
            parts = date.split("-")
            if len(parts) == 3 and len(parts[0]) == 4:
                final_date = f"{parts[2]}.{parts[1]}.{parts[0]}"
        except Exception as e:
            logger.warning(f"Date parsing error: {e}, using original: {date}")
            
    try:
        with Session(engine) as session:
            rule = WatchRule(
                from_station=from_station.strip(),
                to_station=to_station.strip(),
                date_start=final_date,
                date_end=final_date,
                after_time=start_time,
                before_time=end_time,
                ticket_type=ticket_type,
                chat_id=chat_id,
                enabled=True
            )
            session.add(rule)
            session.commit()
            logger.info(f"Created new watcher rule: {rule.id} for {from_station} -> {to_station}")
            
        return RedirectResponse(url="/", status_code=303)
    except Exception as e:
        logger.error(f"Error creating rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create watcher rule")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Authentication middleware - protects all routes except public ones."""
    # Public paths that don't require authentication
    public_paths = ["/login", "/health", "/docs", "/openapi.json", "/redoc"]
    
    if request.url.path in public_paths:
        return await call_next(request)
    
    # Check for authentication token
    token = request.cookies.get("access_token")
    
    if settings.ADMIN_TOKEN:
        if token != settings.ADMIN_TOKEN:
            # For API endpoints, return JSON error instead of redirect
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    {"error": "Unauthorized", "detail": "Authentication required"}, 
                    status_code=401
                )
            # For HTML pages, redirect to login
            return RedirectResponse(url="/login", status_code=303)
             
    return await call_next(request)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, response: Response, password: str = Form(...)):
    if password == settings.ADMIN_TOKEN:
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie(key="access_token", value=password, httponly=True)
        return resp
    else:
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Invalid Admin Token"}, 
            status_code=401
        )

@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp

@app.delete("/rules/{rule_id}", response_class=JSONResponse)
async def delete_rule(rule_id: str, request: Request):
    """Delete a watcher rule."""
    try:
        with Session(engine) as session:
            rule = session.get(WatchRule, rule_id)
            if not rule:
                return JSONResponse(
                    {"success": False, "error": "Rule not found"}, 
                    status_code=404
                )
            
            session.delete(rule)
            session.commit()
            logger.info(f"Deleted watcher rule: {rule_id}")
            
        return JSONResponse({"success": True, "message": "Watcher deleted successfully"})
    except Exception as e:
        logger.error(f"Error deleting rule {rule_id}: {e}", exc_info=True)
        return JSONResponse(
            {"success": False, "error": "Failed to delete watcher"}, 
            status_code=500
        )

@app.delete("/api/history", response_class=JSONResponse)
async def clear_history(request: Request):
    """Clear all ticket history and reset alert keys so trains can be re-notified"""
    from common.database import NotificationHistory
    from common.redis_client import get_redis_client
    
    redis = get_redis_client()
    keys_deleted = 0
    
    with Session(engine) as session:
        # Get all trip snapshots and their associated rule info
        snapshots = session.exec(select(TripSnapshot)).all()
        
        for snap in snapshots:
            # Check if the watcher still exists
            rule = session.get(WatchRule, snap.rule_id)
            if rule:
                # Reset the Redis alert key for this train
                key = f"alert:{snap.rule_id}:{snap.trip_date}:{snap.dep_time}"
                if redis.delete(key):
                    keys_deleted += 1
            
            # Delete the snapshot
            session.delete(snap)
        
        # Also clear notification history
        notifications = session.exec(select(NotificationHistory)).all()
        for notif in notifications:
            session.delete(notif)
            
        session.commit()
        
    return {"success": True, "message": f"History cleared. {keys_deleted} alert keys reset."}

@app.post("/api/reset-alert", response_class=JSONResponse)
async def reset_alert(request: Request):
    """Reset the alert key for a specific trip so it will be re-notified."""
    from common.redis_client import get_redis_client
    
    try:
        body = await request.json()
        rule_id = body.get("rule_id")
        date = body.get("date")
        dep_time = body.get("dep_time")
        
        if not all([rule_id, date, dep_time]):
            return JSONResponse(
                {"success": False, "error": "Missing required parameters: rule_id, date, dep_time"}, 
                status_code=400
            )
        
        # Build the Redis key (same format used in worker/main.py)
        key = f"alert:{rule_id}:{date}:{dep_time}"
        
        redis = get_redis_client()
        deleted = redis.delete(key)
        
        logger.info(f"Reset alert for rule {rule_id}, date {date}, time {dep_time} (key deleted: {deleted})")
        
        return JSONResponse({
            "success": True, 
            "message": f"Alert reset for {date} {dep_time}",
            "key_deleted": bool(deleted)
        })
    except Exception as e:
        logger.error(f"Error resetting alert: {e}", exc_info=True)
        return JSONResponse(
            {"success": False, "error": "Failed to reset alert"}, 
            status_code=500
        )

# --- Dynamic Config Endpoints ---
from pydantic import BaseModel

class ConfigUpdate(BaseModel):
    check_interval_min: int

@app.get("/api/settings/config")
async def get_config():
    from common.redis_client import get_redis_client
    redis = get_redis_client()
    val = redis.get("app:params:check_interval_min")
    return {
        "check_interval_min": int(val) if val else settings.CHECK_INTERVAL_MIN
    }

@app.post("/api/settings/config")
async def update_config(conf: ConfigUpdate):
    """Update application configuration."""
    if not (1 <= conf.check_interval_min <= 10):
        return JSONResponse(
            {"error": "Interval must be between 1 and 10 minutes"}, 
            status_code=400
        )
    
    try:
        from common.redis_client import get_redis_client
        redis = get_redis_client()
        redis.set("app:params:check_interval_min", conf.check_interval_min)
        logger.info(f"Updated check interval to {conf.check_interval_min} minutes")
        return JSONResponse({
            "status": "updated", 
            "value": conf.check_interval_min,
            "message": "Settings saved successfully"
        })
    except Exception as e:
        logger.error(f"Error updating config: {e}", exc_info=True)
        return JSONResponse(
            {"error": "Failed to update settings"}, 
            status_code=500
        )
# --------------------------------

app.include_router(router)

