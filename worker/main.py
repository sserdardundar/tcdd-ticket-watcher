import asyncio
import logging
import sys
from datetime import datetime

from common.config import settings
from common.repository import WatchRulesRepository, TripSnapshotRepository, NotificationHistoryRepository, AlertCacheRepository
from common.notifications import send_telegram
from worker.http_client import TCDDHttpClient

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def run_check(rule: dict, http_client: TCDDHttpClient):
    """
    Checks tickets for a single rule using the HTTP client.
    """
    rule_id = rule.get("id")
    from_station = rule.get("from_station")
    to_station = rule.get("to_station")
    date_start = rule.get("date_start")
    
    logger.info(f"Checking rule {rule_id}: {from_station} -> {to_station} on {date_start}")
    
    try:
        results = http_client.get_trips(from_station, to_station, date_start)
        
        for trip in results:
            dep_time = trip['dep_time']
            arr_time = trip.get('arr_time', '23:59')
            
            # Get seat class info
            economy_seats = trip.get('economy_seats', 0)
            economy_price = trip.get('economy_price', 0.0)
            business_seats = trip.get('business_seats', 0)
            business_price = trip.get('business_price', 0.0)
            loca_seats = trip.get('loca_seats', 0)
            loca_price = trip.get('loca_price', 0.0)
            
            # Time Filter (Dep)
            t_dep = datetime.strptime(dep_time, "%H:%M").time()
            t_after = datetime.strptime(rule.get("after_time", "00:00"), "%H:%M").time()
            t_before = datetime.strptime(rule.get("before_time", "23:59"), "%H:%M").time()
            
            if not (t_after <= t_dep <= t_before):
                continue

            # Time Filter (Arr)
            t_arr = datetime.strptime(arr_time, "%H:%M").time()
            t_arr_after = datetime.strptime(rule.get("arrival_after", "00:00"), "%H:%M").time()
            t_arr_before = datetime.strptime(rule.get("arrival_before", "23:59"), "%H:%M").time()
            
            if not (t_arr_after <= t_arr <= t_arr_before):
                continue
            
            # Apply ticket_type filter
            notify_seats = 0
            notify_price = 0.0
            seat_class = ""
            
            ticket_type = rule.get("ticket_type", "ekonomi")
            min_seats = rule.get("min_seats", 1)
            
            if ticket_type in ("ekonomi", "regular"):
                if economy_seats >= min_seats:
                    notify_seats = economy_seats
                    notify_price = economy_price
                    seat_class = "Ekonomi"
            elif ticket_type == "business":
                if business_seats >= min_seats:
                    notify_seats = business_seats
                    notify_price = business_price
                    seat_class = "Business"
            elif ticket_type == "loca":
                if loca_seats >= min_seats:
                    notify_seats = loca_seats
                    notify_price = loca_price
                    seat_class = "Loca"
            elif ticket_type == "ekonomi_business":
                if economy_seats >= min_seats:
                    notify_seats = economy_seats
                    notify_price = economy_price
                    seat_class = "Ekonomi"
                elif business_seats >= min_seats:
                    notify_seats = business_seats
                    notify_price = business_price
                    seat_class = "Business"
            else:  # "all" mode
                if economy_seats >= min_seats:
                    notify_seats = economy_seats
                    notify_price = economy_price
                    seat_class = "Ekonomi"
                elif business_seats >= min_seats:
                    notify_seats = business_seats
                    notify_price = business_price
                    seat_class = "Business"
                elif loca_seats >= min_seats:
                    notify_seats = loca_seats
                    notify_price = loca_price
                    seat_class = "Loca"
            
            if notify_seats < min_seats:
                logger.debug(f"Skipping trip {dep_time}: only {notify_seats} seats available, need {min_seats}")
                continue
                
            # Dedupe Key
            key = f"alert:{rule_id}:{date_start}:{dep_time}"
            
            # Check Alert Cache (Firestore)
            normalized_price = str(notify_price) or "0"
            cached_val = AlertCacheRepository.get(key)
            
            should_alert = False
            
            if not cached_val:
                should_alert = True
                logger.info(f"✅ New ticket found! Alert key {key} not in cache - will send notification")
            else:
                try:
                    last_price = cached_val.get("last_price", "0")
                    if float(last_price) != float(normalized_price) and float(normalized_price) > 0:
                        should_alert = True
                        logger.info(f"💰 Price changed for {key}: {last_price} -> {normalized_price} - will send notification")
                    else:
                        logger.debug(f"⏭️ Alert key {key} exists with same price ({normalized_price}) - skipping notification")
                except Exception as e:
                    logger.warning(f"Error checking cache: {e}, will send notification")
                    should_alert = True
                    
            if should_alert:
                chat_id = rule.get("chat_id")
                if not chat_id or chat_id <= 0:
                    logger.warning(f"Rule {rule_id} has invalid chat_id ({chat_id}). Skipping notification.")
                    AlertCacheRepository.set(key, str(notify_seats), normalized_price, ttl_hours=6)
                    continue
                
                logger.info(f"🎫 TICKET FOUND for rule {rule_id}! Sending notification to chat_id: {chat_id}")
                
                class_emoji = "💎" if seat_class in ("Business", "Loca") else "🎫"
                msg = (
                    f"{class_emoji} **TICKET FOUND!**\n\n"
                    f"🚄 `{from_station}` ➡️ `{to_station}`\n"
                    f"📅 {date_start}\n\n"
                    f"⏰ **{dep_time}** - {arr_time}\n"
                    f"🎭 Class: **{seat_class}**\n"
                    f"💺 Seats: **{notify_seats}**\n"
                    f"💰 Price: **{notify_price:.2f} TL**\n"
                )
                
                if ticket_type == "all":
                    msg += "\n"
                    if economy_seats > 0:
                        msg += f"📊 _Ekonomi: {economy_seats} seats @ {economy_price:.2f} TL_\n"
                    if business_seats > 0:
                        msg += f"📊 _Business: {business_seats} seats @ {business_price:.2f} TL_\n"
                    if loca_seats > 0:
                        msg += f"📊 _Loca: {loca_seats} seats @ {loca_price:.2f} TL_\n"
                
                reset_data = f"reset:{rule_id}:{date_start}:{dep_time}"
                web_url = "https://ebilet.tcddtasimacilik.gov.tr/"
                play_store_url = "https://play.google.com/store/apps/details?id=tr.gov.tcdd.tasimacilik"
                
                buttons = {
                    "inline_keyboard": [
                        [
                            {"text": "📱 Open E-Bilet App", "url": play_store_url},
                            {"text": "🌐 Buy on Web", "url": web_url}
                        ],
                        [
                            {"text": "🔔 Notify Me Again", "callback_data": reset_data}
                        ]
                    ]
                }
                
                success = send_telegram(msg, chat_id=str(chat_id), reply_markup=buttons)
                if not success:
                    logger.error(f"Failed to send notification for rule {rule_id} to chat_id {chat_id}")
                    continue
                
                # Update Cache (TTL 6 hours)
                AlertCacheRepository.set(key, str(notify_seats), normalized_price, ttl_hours=6)
                
                # Persist Snapshot & History
                TripSnapshotRepository.save({
                    "rule_id": rule_id,
                    "trip_date": date_start,
                    "dep_time": dep_time,
                    "arr_time": arr_time,
                    "train_name": trip.get('train_name', 'TCDD Train'),
                    "seats_available": notify_seats,
                    "price": notify_price,
                    "economy_seats": economy_seats,
                    "economy_price": economy_price,
                    "business_seats": business_seats,
                    "business_price": business_price,
                    "loca_seats": loca_seats,
                    "loca_price": loca_price
                })
                
                NotificationHistoryRepository.save(chat_id, msg)
                
    except Exception as e:
        logger.error(f"Error checking rule {rule_id}: {e}")
        return False
    return True

async def main():
    logger.info("Starting Cloud Run Job: checking all active rules once.")
    
    rules = WatchRulesRepository.get_all_active()
    if not rules:
        logger.info("No active rules found. Exiting.")
        sys.exit(0)
        
    logger.info(f"Found {len(rules)} active rules. Initializing TCDD API Client.")
    http_client = TCDDHttpClient()
    
    # Run sequentially in job for predictability, Cloud Run handles concurrency via multiple executions if needed
    success_count = 0
    failure_count = 0
    
    for rule in rules:
        success = await run_check(rule, http_client)
        if success:
            success_count += 1
        else:
            failure_count += 1

    logger.info(f"Job completed. Rules checked: {len(rules)}. Successes: {success_count}. Failures: {failure_count}.")
    
    if failure_count > 0 and success_count == 0:
        # All failed, alert Cloud Run
        sys.exit(1)
        
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
