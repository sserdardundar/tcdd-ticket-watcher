import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from telegram import Update
import logging

from common.config import settings

from common.repository import WatchRulesRepository, TripSnapshotRepository
from common.utils import STATION_MAP

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="api/templates")

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    rules = WatchRulesRepository.get_all()
    snapshots = TripSnapshotRepository.get_recent(20)
    
    return templates.TemplateResponse(
        "dashboard.html", 
        {"request": request, "rules": rules, "snapshots": snapshots}
    )

@router.get("/rules/new", response_class=HTMLResponse)
async def new_rule_form(request: Request):
    # Pass station map for dropdown
    unique_stations = sorted(list(set(STATION_MAP.values())))
    
    return templates.TemplateResponse(
        "rule_form.html", 
        {"request": request, "rule": None, "stations": unique_stations}
    )

@router.post("/rules", response_class=HTMLResponse)
async def create_rule(
    request: Request,
    from_station: str = Form(...),
    to_station: str = Form(...),
    date_start: str = Form(...), # YYYY-MM-DD from date input
    after_time: str = Form("00:00"),
    before_time: str = Form("23:59"),
    arrival_after: str = Form("00:00"),
    arrival_before: str = Form("23:59"),
    min_seats: int = Form(1),
):
    try:
        y, m, d = date_start.split("-")
        formatted_date = f"{d}.{m}.{y}"
    except ValueError:
        formatted_date = date_start
        
    rule_data = {
        "from_station": from_station,
        "to_station": to_station,
        "date_start": formatted_date,
        "date_end": formatted_date,
        "after_time": after_time,
        "before_time": before_time,
        "arrival_after": arrival_after,
        "arrival_before": arrival_before,
        "min_seats": min_seats,
        "enabled": True,
        "chat_id": 0, # Used when created from web unless changed
        "ticket_type": "ekonomi"
    }
    WatchRulesRepository.create(rule_data)
    return RedirectResponse(url="/", status_code=303)

@router.get("/rules/{rule_id}/delete")
async def delete_rule(rule_id: str):
    WatchRulesRepository.delete(rule_id)
    return RedirectResponse(url="/", status_code=303)

@router.get("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str):
    rule = WatchRulesRepository.get(rule_id)
    if rule:
        WatchRulesRepository.update(rule_id, {"enabled": not rule.get("enabled", False)})
    return RedirectResponse(url="/", status_code=303)

@router.post("/webhook/{token}")
async def telegram_webhook(request: Request, token: str):
    if token != settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
        
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if settings.TELEGRAM_WEBHOOK_SECRET and secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")
    
    bot_app = getattr(request.app.state, "bot_app", None)
    if not bot_app:
        return {"status": "bot not configured"}
        
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return {"status": "error"}
