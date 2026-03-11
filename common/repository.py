import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from google.cloud import firestore

from common.config import settings

logger = logging.getLogger(__name__)

# Initialize Firestore connection. In Cloud Run, it auto-detects credentials.
# Locally, it uses GOOGLE_APPLICATION_CREDENTIALS or the emulator.
db = firestore.Client(project=settings.GCP_PROJECT_ID)

class WatchRulesRepository:
    COLLECTION = "watch_rules"

    @staticmethod
    def create(rule_data: dict) -> str:
        rule_id = str(uuid.uuid4())
        doc_ref = db.collection(WatchRulesRepository.COLLECTION).document(rule_id)
        
        now = datetime.now(timezone.utc)
        
        data = {
            "id": rule_id,
            "created_at": now,
            "updated_at": now,
            **rule_data
        }
        
        doc_ref.set(data)
        return rule_id

    @staticmethod
    def get(rule_id: str) -> dict:
        doc = db.collection(WatchRulesRepository.COLLECTION).document(rule_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    @staticmethod
    def get_all_active() -> list[dict]:
        docs = db.collection(WatchRulesRepository.COLLECTION).where("enabled", "==", True).stream()
        return [doc.to_dict() for doc in docs]
        
    @staticmethod
    def get_by_chat_id(chat_id: int) -> list[dict]:
        docs = db.collection(WatchRulesRepository.COLLECTION).where("chat_id", "==", chat_id).stream()
        return [doc.to_dict() for doc in docs]

    @staticmethod
    def get_all() -> list[dict]:
        # Sort by created_at DESC roughly
        docs = db.collection(WatchRulesRepository.COLLECTION).order_by("created_at", direction=firestore.Query.DESCENDING).stream()
        return [doc.to_dict() for doc in docs]

    @staticmethod
    def update(rule_id: str, updates: dict):
        doc_ref = db.collection(WatchRulesRepository.COLLECTION).document(rule_id)
        updates["updated_at"] = datetime.now(timezone.utc)
        doc_ref.update(updates)

    @staticmethod
    def delete(rule_id: str):
        db.collection(WatchRulesRepository.COLLECTION).document(rule_id).delete()

    @staticmethod
    def delete_by_chat_id(chat_id: int):
        docs = db.collection(WatchRulesRepository.COLLECTION).where("chat_id", "==", chat_id).stream()
        for doc in docs:
            doc.reference.delete()

class TripSnapshotRepository:
    COLLECTION = "trip_snapshots"

    @staticmethod
    def save(snapshot_data: dict) -> str:
        snap_id = str(uuid.uuid4())
        doc_ref = db.collection(TripSnapshotRepository.COLLECTION).document(snap_id)
        
        data = {
            "id": snap_id,
            "last_seen_at": datetime.now(timezone.utc),
            **snapshot_data
        }
        doc_ref.set(data)
        return snap_id

    @staticmethod
    def get_recent(limit: int = 100) -> list[dict]:
        docs = db.collection(TripSnapshotRepository.COLLECTION).order_by("last_seen_at", direction=firestore.Query.DESCENDING).limit(limit).stream()
        return [doc.to_dict() for doc in docs]

    @staticmethod
    def delete_by_rule_id(rule_id: str):
        docs = db.collection(TripSnapshotRepository.COLLECTION).where("rule_id", "==", rule_id).stream()
        for doc in docs:
            doc.reference.delete()

    @staticmethod
    def delete_all():
        docs = db.collection(TripSnapshotRepository.COLLECTION).stream()
        for doc in docs:
            doc.reference.delete()


class NotificationHistoryRepository:
    COLLECTION = "notification_history"

    @staticmethod
    def save(chat_id: int, message: str) -> str:
        notif_id = str(uuid.uuid4())
        doc_ref = db.collection(NotificationHistoryRepository.COLLECTION).document(notif_id)
        data = {
            "id": notif_id,
            "chat_id": chat_id,
            "message": message,
            "created_at": datetime.now(timezone.utc)
        }
        doc_ref.set(data)
        return notif_id

    @staticmethod
    def get_recent_by_chat_id(chat_id: int, limit: int = 5) -> list[dict]:
        docs = db.collection(NotificationHistoryRepository.COLLECTION)\
                 .where("chat_id", "==", chat_id)\
                 .order_by("created_at", direction=firestore.Query.DESCENDING)\
                 .limit(limit).stream()
        return [doc.to_dict() for doc in docs]

    @staticmethod
    def delete_by_chat_id(chat_id: int):
        docs = db.collection(NotificationHistoryRepository.COLLECTION).where("chat_id", "==", chat_id).stream()
        for doc in docs:
            doc.reference.delete()
            
    @staticmethod
    def delete_all():
        docs = db.collection(NotificationHistoryRepository.COLLECTION).stream()
        for doc in docs:
            doc.reference.delete()


class AppConfigRepository:
    COLLECTION = "app_config"
    DOC_ID = "settings"

    @staticmethod
    def get_check_interval_min() -> int:
        doc = db.collection(AppConfigRepository.COLLECTION).document(AppConfigRepository.DOC_ID).get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("check_interval_min", settings.CHECK_INTERVAL_MIN)
        return settings.CHECK_INTERVAL_MIN

    @staticmethod
    def set_check_interval_min(minutes: int):
        doc_ref = db.collection(AppConfigRepository.COLLECTION).document(AppConfigRepository.DOC_ID)
        doc_ref.set({"check_interval_min": minutes}, merge=True)

    @staticmethod
    def get_tcdd_jwts() -> tuple[str, str]:
        doc = db.collection(AppConfigRepository.COLLECTION).document("tcdd_auth").get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("jwt_auth", settings.TCDD_JWT_AUTH), data.get("jwt_user_auth", settings.TCDD_JWT_USER_AUTH)
        return settings.TCDD_JWT_AUTH, settings.TCDD_JWT_USER_AUTH
        
    @staticmethod
    def set_tcdd_jwts(auth: str, user_auth: str):
        doc_ref = db.collection(AppConfigRepository.COLLECTION).document("tcdd_auth")
        doc_ref.set({"jwt_auth": auth, "jwt_user_auth": user_auth, "updated_at": datetime.now(timezone.utc)}, merge=True)


class AlertCacheRepository:
    """Replaces Redis TTL cache for deduping alerts"""
    COLLECTION = "alert_cache"

    @staticmethod
    def get(key: str) -> dict:
        doc = db.collection(AlertCacheRepository.COLLECTION).document(key).get()
        if doc.exists:
            data = doc.to_dict()
            if "expires_at" in data:
                # Check expiration
                if datetime.now(timezone.utc) > data["expires_at"]:
                    doc.reference.delete()
                    return None
            return data
        return None

    @staticmethod
    def set(key: str, last_seats: str, last_price: str, ttl_hours: int = 6):
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        data = {
            "key": key,
            "last_seats": last_seats,
            "last_price": last_price,
            "updated_at": datetime.now(timezone.utc),
            "expires_at": expires_at
        }
        db.collection(AlertCacheRepository.COLLECTION).document(key).set(data)
        
    @staticmethod
    def delete(key: str) -> bool:
        doc_ref = db.collection(AlertCacheRepository.COLLECTION).document(key)
        if doc_ref.get().exists:
            doc_ref.delete()
            return True
        return False

    @staticmethod
    def clear_all():
        docs = db.collection(AlertCacheRepository.COLLECTION).stream()
        for doc in docs:
            doc.reference.delete()
