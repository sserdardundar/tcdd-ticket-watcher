from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import calendar
from datetime import date, timedelta

def create_calendar(year=None, month=None):
    """
    Create an InlineKeyboardMarkup for the given year and month.
    """
    now = date.today()
    if year is None: year = now.year
    if month is None: month = now.month
    
    keyboard = []
    
    # Header Row: Month and Year
    month_name = calendar.month_name[month]
    keyboard.append([InlineKeyboardButton(f"{month_name} {year}", callback_data="CAL_IGNORE")])
    
    # Week Days
    week_days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    keyboard.append([InlineKeyboardButton(day, callback_data="CAL_IGNORE") for day in week_days])
    
    # Calendar Rows
    my_calendar = calendar.monthcalendar(year, month)
    for week in my_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
            else:
                s_date = date(year, month, day)
                # Mark past days as ignore, unless it's today (handled logic elsewhere but visual cue is nice)
                if s_date < now:
                    row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE")) 
                else:
                    # Callback format: CAL_DATE|YYYY-MM-DD
                    row.append(InlineKeyboardButton(str(day), callback_data=f"CAL_DATE|{s_date.isoformat()}"))
        keyboard.append(row)
        
    # Navigation Row
    nav_row = []
    
    # Previous Month
    prev_month = month - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1
        
    # Only show prev if it's not in the past relative to current month (approx)
    # Actually, simplistic check: if prev month end < today, maybe disable?
    # Simple logic: Always show prev/next for now, but strictly we could limit.
    nav_row.append(InlineKeyboardButton("<", callback_data=f"CAL_NAV|{prev_year}|{prev_month}"))
    
    # Ignore center
    nav_row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
    
    # Next Month
    next_month = month + 1
    next_year = year
    if next_month == 13:
        next_month = 1
        next_year += 1
    nav_row.append(InlineKeyboardButton(">", callback_data=f"CAL_NAV|{next_year}|{next_month}"))
    
    keyboard.append(nav_row)
    
    return InlineKeyboardMarkup(keyboard)

def process_calendar_selection(update, context):
    """
    Process the callback query from the calendar.
    Returns (selected, date_obj)
    selected: True if a date was selected, False if navigation/ignore
    date_obj: The date object if selected
    """
    query = update.callback_query
    data = query.data
    
    if data == "CAL_IGNORE":
        query.answer()
        return False, None
        
    if data.startswith("CAL_NAV|"):
        _, y, m = data.split("|")
        new_markup = create_calendar(int(y), int(m))
        query.edit_message_reply_markup(reply_markup=new_markup)
        query.answer()
        return False, None
        
    if data.startswith("CAL_DATE|"):
        _, date_str = data.split("|")
        return True, date.fromisoformat(date_str)
        
    return False, None
