# 🚄 TCDD Ticket Watcher

A dockerized application to monitor TCDD (Turkish State Railways) train tickets and notify you via Telegram when seats become available.

![Dashboard Preview](docs/dashboard.png)

## ✨ Features

### Core Functionality
- **🔍 Fast HTTP API Client**: Uses direct TCDD API endpoints instead of heavy web scraping
- **🎫 Ticket Types**: Filter by Ekonomi only or All Classes (Ekonomi + Business)
- **🤖 Telegram Webhooks**: Full-featured bot with interactive menus responding instantly
- **🌐 Web Dashboard**: Modern glassmorphism UI to manage watchers and view tickets
- **☁️ Cloud Native**: Fully designed to run Serverless on Google Cloud Run and Firestore

### Seat Class Support
| Mode | Description |
|------|-------------|
| **Regular** | Only notifies for Ekonomi (economy) class seats |
| **All Classes** | Notifies for Ekonomi, or Business class as fallback |

> ⚠️ Wheelchair seats (TEKERLEKLİ SANDALYE) are always excluded from notifications.

---

## 📋 Prerequisites

- **Google Cloud Platform** (GCP) account with BILLING enabled
- **gcloud CLI** installed and authenticated
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Your Telegram Chat ID (get it from [@userinfobot](https://t.me/userinfobot))

---

## 🚀 Deployment (Google Cloud)

### 1. Enable Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com
```

### 2. Setup Firestore

Navigate to GCP Console > Firestore and create a **Native Mode** database in your region.

### 3. Store Secrets

Set your confidential values in Secret Manager:

```bash
echo -n "YOUR_TELEGRAM_TOKEN" | gcloud secrets create telegram-token --data-file=-
echo -n "YOUR_ADMIN_PASSWORD" | gcloud secrets create admin-token --data-file=-
```

### 4. Deploy

Clone this repository and run the deployment script. Be sure to update `scripts/gcp_deploy.sh` with your `PROJECT_ID`!

```bash
git clone https://github.com/yourusername/tcdd-ticket-watcher.git
cd tcdd-ticket-watcher

chmod +x scripts/gcp_deploy.sh
./scripts/gcp_deploy.sh
```

### 5. Finalize Webhook Setup

Once deployed, copy your API Service URL and set the Telegram webhook:

```bash
curl -X POST https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook?url=<CLOUD_RUN_API_URL>/webhook/<TELEGRAM_TOKEN>
```

---

## 🤖 Telegram Bot Usage

### Main Menu

```
🎫 New Watcher   | 📋 My Watchers
📜 History       | 🗑️ Clear History
              ❓ Help
```

### Creating a Watcher (5 Steps)

1. **📍 Departure Station** - Select where you're leaving from
2. **🎯 Arrival Station** - Select your destination
3. **📅 Date** - Choose Today, Tomorrow, +3 days, or enter custom date
4. **⏰ Time Window** - Morning, Afternoon, Evening, or All Day
5. **🎭 Ticket Type** - Regular (Ekonomi) or All Classes

### Notification Example

```
🎫 TICKET FOUND!

🚄 Ankara Gar ➡️ İstanbul(Söğütlüçeşme)
📅 25.12.2025

⏰ 19:50 - 23:58
🎭 Class: Ekonomi
💺 Seats: 192
💰 Price: 780.00 TL

[🛒 Buy Ticket] [🔔 Notify Again]
```

### Managing Watchers

- View all watchers with **📋 My Watchers**
- **⏸ Pause / ▶️ Resume** individual watchers
- **🗑 Delete** watchers you no longer need
- **🗑️ Clear History** removes all notification history

---

## 🌐 Web Dashboard

### Features

- **Premium Dark Theme** with glassmorphism effects
- **Real-time Updates** via live polling
- **Quick Date Selection** buttons (Today, Tomorrow, +1 Week)
- **Ticket Type Selection** dropdown
- **Clear History** button to reset all ticket history
- **Relook Button** to re-enable notifications for specific trains

### Creating a Watcher via Web

1. Go to http://localhost:8000
2. Login with your `ADMIN_TOKEN` password
3. Fill in the "New Watcher" form:
   - From/To stations
   - Date
   - Departure time window
   - **Ticket Type** (Regular or All Classes)
   - Your Telegram Chat ID
3. Click "Create Watcher"

### Found Tickets Table

Shows all discovered tickets with:
- Route and date
- Departure time and train name
- **Seat breakdown** (🎫 Ekonomi / 💎 Business)
- **Price info** for each class
- Quick actions: Relook, Buy

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Google Cloud Platform                │
├─────────────┬─────────────┬────────────┬────────────┤
│ Cloud Run   │ Cloud Run   │ Cloud      │ Secret     │
│ Service API │ Job Worker  │ Scheduler  │ Manager    │
│ (FastAPI)   │ (Scheduler) │ (Trigger)  │            │
└─────────────┴─────────────┴────────────┴────────────┘
```

| Component | Description |
|-----------|-------------|
| `API Service` | FastAPI app serving the dashboard and handling Telegram webhooks |
| `Worker Job` | Background job that spins up, checks tickets, and safely exits |
| `Firestore` | Native mode NoSQL datastore for persistence and dedup caching |

### Data Persistence (Firestore)

- `watch_rules` - User-defined ticket watcher configs
- `trip_snapshots` - Log of discovered available tickets
- `alert_cache` - Deduplication cache so you aren't spammed

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GOOGLE_CLOUD_PROJECT` | Your GCP Project ID | ✅ |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | ✅ |
| `TELEGRAM_CHAT_ID` | Default chat ID for notifications | ✅ |
| `ADMIN_TOKEN` | Password for web dashboard access | ✅ |

---

## 🔧 Deployment
Use the provided `scripts/gcp_deploy.sh` to fully configure your Cloud Run setup using Artifact Registry and Cloud Scheduler.

Make sure to set your secrets in Secret Manager before executing!

## 📝 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard (requires token) |
| GET | `/api/stats` | Get rules and found tickets |
| POST | `/rules` | Create new watcher |
| DELETE | `/rules/{id}` | Delete a watcher |
| DELETE | `/api/history` | Clear all ticket history |
| POST | `/api/reset-alert` | Re-enable notification for a trip |

---

## 🛠️ Troubleshooting

### Bot not responding
- Check if your `TELEGRAM_BOT_TOKEN` in Secret Manager is valid.
- Verify your webhook is correctly configured by visiting `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
- View API logs in **Google Cloud Logging** (Cloud Run Service > Logs).

### No tickets found
- Verify TCDD website is accessible temporarily.
- Check Worker logs in **Google Cloud Logging** (Cloud Run Jobs > Logs).
- Ensure your Cloud Scheduler is set to trigger successfully and has the necessary permissions.

### Dashboard not loading
- Ensure you have deployed the Cloud Run service successfully.
- Check Cloud Run Service logs.

---

## 📄 License

MIT License - feel free to use and modify!

---

## 🙏 Acknowledgments

- [TCDD](https://ebilet.tcddtasimacilik.gov.tr/) for the ticket system
- [python-telegram-bot](https://python-telegram-bot.org/) for Telegram integration
