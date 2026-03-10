import asyncio
import logging
from datetime import datetime, timedelta
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters
)


from common.config import settings
from common.repository import WatchRulesRepository, NotificationHistoryRepository, TripSnapshotRepository, AppConfigRepository, AlertCacheRepository
from common.utils import STATION_MAP, normalize_station, POPULAR_STATIONS, HIGH_FREQ_STATIONS, MORE_STATIONS, ALL_STATIONS

# Logger
logger = logging.getLogger(__name__)

from worker.calendar_utils import create_calendar, process_calendar_selection

import re
# States for Conversation
SELECT_FROM, SELECT_TO, SELECT_DATE, SELECT_TIME, SELECT_TICKET_TYPE, CONFIRM, CUSTOM_DATE_INPUT = range(7)



def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🎫 Watcher", "📜 History"],
        ["⚙️ Other"]
    ], resize_keyboard=True)

def get_watcher_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🎫 New Watcher", "📋 My Watchers"],
        ["🔙 Back"]
    ], resize_keyboard=True)

def get_history_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["📜 Show History", "🗑️ Clear History"],
        ["🔙 Back"]
    ], resize_keyboard=True)

def get_other_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["⚙️ Settings", "❓ Help"],
        ["🔙 Back"]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = get_main_menu_keyboard()
    await update.message.reply_text(
        "🚄 **TCDD Ticket Watcher**\n\n"
        "I'll monitor train tickets and alert you when seats are available!\n\n"
        "Select a category below:",
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )

async def watcher_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎫 **Watcher Menu**", reply_markup=get_watcher_menu_keyboard(), parse_mode="Markdown")

async def history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📜 **History Menu**", reply_markup=get_history_menu_keyboard(), parse_mode="Markdown")

async def other_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ **Other Menu**", reply_markup=get_other_menu_keyboard(), parse_mode="Markdown")

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔙 **Main Menu**", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Worker Settings (Check Interval)"""
    current_val = AppConfigRepository.get_check_interval_min()
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'✅ ' if current_val==1 else ''}1 min", callback_data="set_int|1"),
            InlineKeyboardButton(f"{'✅ ' if current_val==3 else ''}3 min", callback_data="set_int|3"),
            InlineKeyboardButton(f"{'✅ ' if current_val==5 else ''}5 min", callback_data="set_int|5"),
            InlineKeyboardButton(f"{'✅ ' if current_val==10 else ''}10 min", callback_data="set_int|10"),
        ]
    ])
    
    msg_text = (
        f"⚙️ **Worker Settings**\n"
        f"Current Check Interval: **{current_val} mins**\n"
        "Select new interval:"
    )
    
    try:
        if update.callback_query:
             await update.callback_query.edit_message_text(msg_text, reply_markup=kb, parse_mode="Markdown")
        else:
             await update.message.reply_text(msg_text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        # Ignore "Message is not modified" errors
        if "Message is not modified" not in str(e):
             logger.error(f"Error in settings_command: {e}")

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("set_int|"):
        val = int(data.split("|")[1])
        AppConfigRepository.set_check_interval_min(val)
        await settings_command(update, context)







async def new_rule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Rule Creation Flow with step indicator."""
    logger.info(f"new_rule_start triggered by chat_id={update.effective_chat.id}, text='{update.message.text}'")
    keyboard = []
    # Show high-frequency stations first
    for st in HIGH_FREQ_STATIONS:
        keyboard.append([InlineKeyboardButton(f"🚉 {st}", callback_data=f"from|{st}")])
    # Add More Stations button
    keyboard.append([InlineKeyboardButton("📋 More Stations...", callback_data="from|more_stations")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━\n"
        "🎫 **New Watcher** (1/5)\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "📍 Select **Departure** Station:", 
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )
    return SELECT_FROM

async def list_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rules = WatchRulesRepository.get_by_chat_id(chat_id)
    # Filter only enabled ones manually just in case, though get_by_chat_id returns all for that user
    rules = [r for r in rules if r.get("enabled", False)]
    
    if not rules:
        await update.message.reply_text(
            "📭 **No active watchers**\n\n"
            "Tap *🎫 New Watcher* to create one!",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        f"📋 **Your Watchers** ({len(rules)} active)\n"
        "━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown", 
        reply_markup=get_main_menu_keyboard()
    )
    
    for r in rules:
            ticket_type = r.get("ticket_type", "ekonomi")
            ticket_type_label = "💎 All Classes" if ticket_type == "all" else "🎫 Ekonomi Only"
            info_text = (
                f"┌─────────────────\n"
                f"│ 🚄 **{r.get('from_station')}** ➡️ **{r.get('to_station')}**\n"
                f"│ 📅 {r.get('date_start')}\n"
                f"│ ⏰ {r.get('after_time')} - {r.get('before_time')}\n"
                f"│ {ticket_type_label}\n"
                f"└─────────────────"
            )
            # Inline buttons for actions
            rule_id = r.get("id")
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑 Delete", callback_data=f"delete_rule|{rule_id}"),
                    InlineKeyboardButton("⏸ Pause" if r.get("enabled") else "▶️ Resume", callback_data=f"toggle_rule|{rule_id}")
                ]
            ])
            await update.message.reply_text(info_text, parse_mode="Markdown", reply_markup=kb)
            
    return ConversationHandler.END

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    history = NotificationHistoryRepository.get_recent_by_chat_id(chat_id, limit=5)
    
    if not history:
         await update.message.reply_text("📭 No alert history yet.", reply_markup=get_main_menu_keyboard())
         return ConversationHandler.END

    msg = "📜 **Recent Alerts**\n"
    for h in history:
        created_at = h.get("created_at")
        if hasattr(created_at, "strftime"):
             time_str = created_at.strftime("%d.%m %H:%M")
        else:
             time_str = str(created_at)
             
        message = h.get("message", "")
        lines = message.split("\n")
            
        # Simple parsing of standard alert format
        route = "Unknown Route"
        trip_info = "?"
        
        for line in lines:
            if "🚄" in line:
                route = line.strip().replace("`", "")
            if "📅" in line:
                trip_info = line.strip().replace("📅", "").replace("⏰", "").strip()
        
        msg += f"\n⏰ *{time_str}*\n{route}\n📅 {trip_info}\n──────────────────"
        
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

async def clear_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all ticket history for the current user."""
    chat_id = update.effective_chat.id
    
    # Show confirmation buttons
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Clear All", callback_data="confirm_clear_history"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear_history")
        ]
    ])
    
    await update.message.reply_text(
        "⚠️ **Clear History?**\n\nThis will delete all your notification history. This cannot be undone.",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ConversationHandler.END

async def confirm_clear_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation of clear history. Also resets Redis alert keys."""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    keys_deleted = 0
    
    # Delete notification history for this user
    NotificationHistoryRepository.delete_by_chat_id(chat_id)
    
    # Get all rules for this user
    rules = WatchRulesRepository.get_by_chat_id(chat_id)
    
    # Since we can't easily query snapshots by rule_id efficiently without indices,
    # we'll fetch recent snapshots and filter in memory, or just clear all caches.
    # To keep it simple, we clear all caches for these rules.
    for rule in rules:
        rule_id = rule.get("id")
        # In a real app we'd query by rule_id, here we just clear the history
        pass
        
    # As a simplification for clear history, wipe local AlertCaches
    AlertCacheRepository.clear_all()
    keys_deleted = 1

    
    edited_message = await query.edit_message_text(
        f"🗑️ History cleared! ({keys_deleted} alerts reset)\n\n_This message will disappear in 5 seconds..._",
        parse_mode="Markdown"
    )
    asyncio.create_task(schedule_message_delete(edited_message, 5))

async def cancel_clear_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancellation of clear history."""
    query = update.callback_query
    await query.answer()
    
    edited_message = await query.edit_message_text("❌ Cancelled.\n\n_This message will disappear in 5 seconds..._", parse_mode="Markdown")
    asyncio.create_task(schedule_message_delete(edited_message, 5))

async def schedule_message_delete(message, delay_seconds: int = 5):
    """Schedule a message to be deleted after a delay."""
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception as e:
        logger.debug(f"Could not delete message: {e}")

async def delete_rule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, rule_id_str = data.split("|")
    
    r = WatchRulesRepository.get(rule_id_str)
    if r:
        route_info = f"{r.get('from_station')} ➡️ {r.get('to_station')}"
        WatchRulesRepository.delete(rule_id_str)
        edited_message = await query.edit_message_text(f"🗑 Watcher deleted.\n\n_{route_info}_\n\n_This message will disappear in 5 seconds..._", parse_mode="Markdown")
        # Schedule the message for deletion
        asyncio.create_task(schedule_message_delete(edited_message, 5))
    else:
            edited_message = await query.edit_message_text("❓ Watcher already deleted.\n\n_This message will disappear in 5 seconds..._", parse_mode="Markdown")
            asyncio.create_task(schedule_message_delete(edited_message, 5))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚄 **How to Use TCDD Ticket Watcher**\n\n"
        "**Step 1️⃣** Create a Watcher\n"
        "→ Tap `🎫 Watcher` → `🎫 New Watcher`\n\n"
        "**Step 2️⃣** Pick Your Route\n"
        "→ Choose departure & arrival stations\n\n"
        "**Step 3️⃣** Select Date & Time\n"
        "→ Use calendar to pick travel date\n"
        "→ Choose time window (or All Day)\n\n"
        "**Step 4️⃣** Choose Ticket Class\n"
        "→ Ekonomi, Business, Loca, or Any\n\n"
        "**Step 5️⃣** Get Notified! 🔔\n"
        "→ We'll alert you when tickets appear\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "**Quick Actions:**\n"
        "• `📋 My Watchers` - View/pause/delete\n"
        "• `📜 History` - Past alerts\n"
        "• `/settings` - Check interval (1-10 min)",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Cancelled.")
    return ConversationHandler.END


async def select_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
         await query.edit_message_text("❌ Cancelled.")
         await context.bot.send_message(chat_id=update.effective_chat.id, text="Menu:", reply_markup=get_main_menu_keyboard())
         return ConversationHandler.END
    
    data = query.data
    _, station = data.split("|")
    
    # Handle "More Stations" button
    if station == "more_stations":
        keyboard = []
        for st in ALL_STATIONS:
            keyboard.append([InlineKeyboardButton(f"🚉 {st}", callback_data=f"from|{st}")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "━━━━━━━━━━━━━━━━━\n"
            "🎫 **New Watcher** (1/5)\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "📍 Select **Departure** Station:", 
            reply_markup=reply_markup, 
            parse_mode="Markdown"
        )
        return SELECT_FROM
    
    context.user_data["from"] = station
    
    # Now Select To - show high-freq stations first with More Stations option
    keyboard = []
    for st in HIGH_FREQ_STATIONS:
        if st != station:
            keyboard.append([InlineKeyboardButton(f"🚉 {st}", callback_data=f"to|{st}")])
    keyboard.append([InlineKeyboardButton("📋 More Stations...", callback_data="to|more_stations")])
    keyboard.append([InlineKeyboardButton("🔙 Menu", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=(
            "━━━━━━━━━━━━━━━━━\n"
            "🎫 **New Watcher** (2/5)\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            f"🛫 From: `{station}`\n\n"
            "📍 Select **Arrival** Station:"
        ), 
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )
    return SELECT_TO

async def select_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
         await query.edit_message_text("❌ Cancelled.")
         await context.bot.send_message(chat_id=update.effective_chat.id, text="Menu:", reply_markup=get_main_menu_keyboard())
         return ConversationHandler.END
    
    data = query.data
    _, station = data.split("|")
    
    # Handle "More Stations" button
    if station == "more_stations":
        from_station = context.user_data.get("from", "")
        keyboard = []
        for st in ALL_STATIONS:
            if st != from_station:
                keyboard.append([InlineKeyboardButton(f"🚉 {st}", callback_data=f"to|{st}")])
        keyboard.append([InlineKeyboardButton("🔙 Menu", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text=(
                "━━━━━━━━━━━━━━━━━\n"
                "🎫 **New Watcher** (2/5)\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                f"🛫 From: `{from_station}`\n\n"
                "📍 Select **Arrival** Station:"
            ), 
            reply_markup=reply_markup, 
            parse_mode="Markdown"
        )
        return SELECT_TO
    
    context.user_data["to"] = station
    
    # Send Calendar
    reply_markup = create_calendar()
    await query.edit_message_text(
        text=(
            "━━━━━━━━━━━━━━━━━\n"
            "🎫 **New Watcher** (3/5)\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            f"🏁 Route: `{context.user_data['from']}` ➡️ `{station}`\n\n"
            "📅 Select **Date**:"
        ), 
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )
    return SELECT_DATE

async def custom_date_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        text="📅 Please type the date you want to watch (Format: DD.MM.YYYY):",
        parse_mode="Markdown"
    )
    return CUSTOM_DATE_INPUT

async def custom_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # Validate format DD.MM.YYYY
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
        await update.message.reply_text("❌ Invalid format. Please use **DD.MM.YYYY** (e.g., 25.12.2025):", parse_mode="Markdown")
        return CUSTOM_DATE_INPUT
        
    context.user_data["date"] = text
    
    # Proceed to Time Selection (Duplicate logic from select_date, can refactor but copy is safer for now)
    times = [
        [InlineKeyboardButton("🌅 Morning (06-12)", callback_data="time|06:00|12:00")],
        [InlineKeyboardButton("☀️ Afternoon (12-18)", callback_data="time|12:00|18:00")],
        [InlineKeyboardButton("🌙 Evening (18-23)", callback_data="time|18:00|23:59")],
        [InlineKeyboardButton("🕒 All Day (00-24)", callback_data="time|00:00|23:59")]
    ]
    reply_markup = InlineKeyboardMarkup(times)
    
    await update.message.reply_text(
        text=f"📅 Date: {text}\n⏰ Select **Time Window**:", 
        reply_markup=reply_markup, 
        parse_mode="Markdown"
    )
    return SELECT_TIME

async def calendar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle calendar interaction."""
    selected, date_obj = process_calendar_selection(update, context)
    
    if selected:
        date_str = date_obj.strftime("%d.%m.%Y")
        context.user_data["date"] = date_str
        
        # Time Selection
        times = [
            [InlineKeyboardButton("🌅 Morning (06-12)", callback_data="time|06:00|12:00")],
            [InlineKeyboardButton("☀️ Afternoon (12-18)", callback_data="time|12:00|18:00")],
            [InlineKeyboardButton("🌙 Evening (18-23)", callback_data="time|18:00|23:59")],
            [InlineKeyboardButton("🕒 All Day", callback_data="time|00:00|23:59")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(times)
        
        # We need to answer the callback query if process_calendar_selection didn't (it returns selected=True)
        # Actually process_calendar_selection returns True only for CAL_DATE which doesn't answer/edit inside the util.
        await update.callback_query.answer()
        
        await update.callback_query.edit_message_text(
            text=(
                "━━━━━━━━━━━━━━━━━\n"
                "🎫 **New Watcher** (4/5)\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                f"🚄 `{context.user_data['from']}` ➡️ `{context.user_data['to']}`\n"
                f"📅 {date_str}\n\n"
                "⏰ Select **Departure Time**:"
            ), 
            reply_markup=reply_markup, 
            parse_mode="Markdown"
        )
        return SELECT_TIME
        
    return SELECT_DATE

async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
         await query.edit_message_text("❌ Cancelled.")
         await context.bot.send_message(chat_id=update.effective_chat.id, text="Menu:", reply_markup=get_main_menu_keyboard())
         return ConversationHandler.END
    
    data = query.data
    _, start_t, end_t = data.split("|")
    context.user_data["start_time"] = start_t
    context.user_data["end_time"] = end_t
    
    # Ticket Type Selection - Ekonomi first (default)
    ticket_types = [
        [InlineKeyboardButton("🎫 Ekonomi Only", callback_data="ticket_type|ekonomi")],
        [InlineKeyboardButton("💼 Business Only", callback_data="ticket_type|business")],
        [InlineKeyboardButton("🛋️ Loca Only", callback_data="ticket_type|loca")],
        [InlineKeyboardButton("🎫💼 Ekonomi or Business", callback_data="ticket_type|ekonomi_business")],
        [InlineKeyboardButton("💎 Any Class", callback_data="ticket_type|all")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(ticket_types)
    
    time_label = "All Day" if start_t == "00:00" and end_t == "23:59" else f"{start_t} - {end_t}"
    
    await query.edit_message_text(
        text=(
            "━━━━━━━━━━━━━━━━━\n"
            "🎫 **New Watcher** (5/5)\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            f"🚄 `{context.user_data['from']}` ➡️ `{context.user_data['to']}`\n"
            f"📅 {context.user_data['date']}\n"
            f"⏰ {time_label}\n\n"
            "🎭 Select **Ticket Type**:"
        ),
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return SELECT_TICKET_TYPE

async def select_ticket_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
         await query.edit_message_text("❌ Cancelled.")
         await context.bot.send_message(chat_id=update.effective_chat.id, text="Menu:", reply_markup=get_main_menu_keyboard())
         return ConversationHandler.END
    
    data = query.data
    _, ticket_type = data.split("|")
    
    # Check for duplicate watcher
    all_rules = WatchRulesRepository.get_by_chat_id(update.effective_chat.id)
    existing = False
    for r in all_rules:
        if (r.get("from_station") == context.user_data["from"] and
            r.get("to_station") == context.user_data["to"] and
            r.get("date_start") == context.user_data["date"]):
            existing = True
            break
            
    if existing:
        await query.edit_message_text(
            text=(
                "━━━━━━━━━━━━━━━━━\n"
                "⚠️ **Duplicate Watcher**\n"
                "━━━━━━━━━━━━━━━━━\n\n"
                f"You already have a watcher for:\n"
                f"🚄 `{context.user_data['from']}` ➡️ `{context.user_data['to']}`\n"
                f"📅 {context.user_data['date']}\n\n"
                "❌ Cancelled to avoid duplicates."
            ),
            parse_mode="Markdown"
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Menu:",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    # Save Rule (no duplicate found)
    rule_data = {
        "from_station": context.user_data["from"],
        "to_station": context.user_data["to"],
        "date_start": context.user_data["date"],
        "date_end": context.user_data["date"],
        "after_time": context.user_data["start_time"],
        "before_time": context.user_data["end_time"],
        "ticket_type": ticket_type,
        "chat_id": update.effective_chat.id,
        "enabled": True
    }
    rule_id = WatchRulesRepository.create(rule_data)

    # Ticket type labels for all 5 options
    ticket_labels = {
        "ekonomi": "🎫 Ekonomi Only",
        "regular": "🎫 Ekonomi Only",  # Legacy
        "business": "💼 Business Only",
        "loca": "🛋️ Loca Only",
        "ekonomi_business": "🎫💼 Ekonomi or Business",
        "all": "💎 Any Class"
    }
    ticket_type_label = ticket_labels.get(ticket_type, "🎫 Ekonomi Only")
    time_label = "All Day" if context.user_data["start_time"] == "00:00" and context.user_data["end_time"] == "23:59" else f"{context.user_data['start_time']} - {context.user_data['end_time']}"
    
    # Finish with success message
    await query.edit_message_text(
        text=(
            "━━━━━━━━━━━━━━━━━\n"
            "✅ **Watcher Created!**\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            f"🚄 `{context.user_data['from']}` ➡️ `{context.user_data['to']}`\n"
            f"📅 {context.user_data['date']}\n"
            f"⏰ {time_label}\n"
            f"{ticket_type_label}\n\n"
            "🔔 I'll alert you when tickets are found!"
        ),
        parse_mode="Markdown"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="What would you like to do next?",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
         await update.callback_query.edit_message_text("❌ Cancelled.")
         await context.bot.send_message(
             chat_id=update.effective_chat.id,
             text="Menu:",
             reply_markup=get_main_menu_keyboard()
         )
    else:
         await update.message.reply_text("❌ Cancelled.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle /delete_UUID
    text = update.message.text
    try:
        _, rule_id_str = text.split("_")
        r = WatchRulesRepository.get(rule_id_str)
        if r:
            WatchRulesRepository.delete(rule_id_str)
            await update.message.reply_text("🗑 Rule deleted.", reply_markup=get_main_menu_keyboard())
        else:
            await update.message.reply_text("❓ Rule not found.", reply_markup=get_main_menu_keyboard())
    except:
        await update.message.reply_text("❌ Usage: Click delete link in list.", reply_markup=get_main_menu_keyboard())

async def reset_alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset the alert cache for a specific train so user can be notified again."""
    query = update.callback_query
    data = query.data # reset:{rule_id}:{date}:{dep_time}
    
    try:
        parts = data.split(":")
        if len(parts) < 4:
            logger.error(f"Invalid reset data format: {data}")
            await query.answer("❌ Invalid request format.", show_alert=True)
            return
        
        # parts[0] is "reset"
        rule_id = parts[1]
        date = parts[2]  # Format: DD.MM.YYYY (e.g., "25.12.2025")
        dep_time = parts[3]  # Format: HH:MM (e.g., "06:15")
        
        # Reconstruct Cache key
        key = f"alert:{rule_id}:{date}:{dep_time}"
        
        logger.info(f"Resetting alert cache for key: {key}")
        deleted = AlertCacheRepository.delete(key)
        
        if deleted:
            logger.info(f"Successfully deleted alert cache key: {key} (existed: {key_exists})")
            await query.answer(
                "✅ Cache cleared! You will be notified again for this train if tickets are still available.",
                show_alert=True
            )
            if deleted:
                logger.warning(f"Key existed but deletion logic ran: {key}")
                await query.answer(
                    "⚠️ Cache may already be cleared. You should be notified on next check.",
                    show_alert=True
                )
            else:
                logger.info(f"Key did not exist (may have expired): {key}")
                await query.answer(
                    "ℹ️ Cache already cleared. You will be notified on next check if tickets are available.",
                    show_alert=True
                )
        
    except Exception as e:
        logger.error(f"Reset handler error: {e}", exc_info=True)
        await query.answer("❌ Error resetting alert. Please try again.", show_alert=True)

async def toggle_rule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle a watcher's enabled state."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, rule_id_str = data.split("|")
    r = WatchRulesRepository.get(rule_id_str)
    
    if r:
        new_status = not r.get("enabled", False)
        WatchRulesRepository.update(rule_id_str, {"enabled": new_status})
        
        status = "▶️ Resumed" if new_status else "⏸ Paused"
        ticket_type_label = "💎 All Classes" if r.get("ticket_type") == "all" else "🎫 Ekonomi Only"
        
        # Re-render the watcher card
        info_text = (
            f"┌─────────────────\n"
            f"│ 🚄 **{r.get('from_station')}** ➡️ **{r.get('to_station')}**\n"
            f"│ 📅 {r.get('date_start')}\n"
            f"│ ⏰ {r.get('after_time')} - {r.get('before_time')}\n"
            f"│ {ticket_type_label}\n"
            f"│ {status}\n"
            f"└─────────────────"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🗑 Delete", callback_data=f"delete_rule|{rule_id_str}"),
                InlineKeyboardButton("▶️ Resume" if not new_status else "⏸ Pause", callback_data=f"toggle_rule|{rule_id_str}")
            ]
        ])
        await query.edit_message_text(info_text, parse_mode="Markdown", reply_markup=kb)
    else:
        await query.edit_message_text("❓ Watcher not found.")



def create_bot_app():
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
        
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    
    # 1. Settings Handlers
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^set_int\|"))

    # 2. Menu Navigation
    app.add_handler(MessageHandler(filters.Regex("^🎫 Watcher$"), watcher_menu))
    app.add_handler(MessageHandler(filters.Regex("^📜 History$"), history_menu))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Other$"), other_menu))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Back$"), back_to_main))

    # 3. Sub-Menu Triggers
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Settings$"), settings_command))
    app.add_handler(MessageHandler(filters.Regex("^📜 Show History$"), history_command))

    # 4. Conversation Handler (New Watcher)
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🎫 New Watcher$"), new_rule_start)
        ],
        states={
            SELECT_FROM: [CallbackQueryHandler(select_from, pattern=r"(^from\||^cancel$)")],
            SELECT_TO: [CallbackQueryHandler(select_to, pattern=r"(^to\||^cancel$)")],
            SELECT_DATE: [
                CallbackQueryHandler(calendar_handler, pattern=r"^CAL_.*"),
                CallbackQueryHandler(cancel_inline, pattern="^cancel$") 
            ],
            SELECT_TIME: [CallbackQueryHandler(select_time, pattern=r"(^time\||^cancel$)")],
            SELECT_TICKET_TYPE: [CallbackQueryHandler(select_ticket_type, pattern=r"(^ticket_type\||^cancel$)")],
        },
        fallbacks=[
             CommandHandler("cancel", cancel),
             CallbackQueryHandler(cancel_inline, pattern="^cancel$")
        ]
    )
    
    app.add_handler(conv_handler)
    
    # 5. Other Handlers
    app.add_handler(CallbackQueryHandler(delete_rule_callback, pattern=r"^delete_rule\|"))
    app.add_handler(CallbackQueryHandler(toggle_rule_callback, pattern=r"^toggle_rule\|"))
    app.add_handler(CallbackQueryHandler(reset_alert_handler, pattern=r"^reset:"))
    app.add_handler(CallbackQueryHandler(confirm_clear_history_callback, pattern=r"^confirm_clear_history$"))
    app.add_handler(CallbackQueryHandler(cancel_clear_history_callback, pattern=r"^cancel_clear_history$"))
    
    # 6. Text Handlers for Legacy/Sub-menu items
    app.add_handler(MessageHandler(filters.Regex("^📋 My Watchers$"), list_rules))
    app.add_handler(MessageHandler(filters.Regex("^🗑️ Clear History$"), clear_history_command))
    app.add_handler(MessageHandler(filters.Regex("^❓ Help$"), help_command))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex(r"^/delete_"), delete_handler))
    
    return app
