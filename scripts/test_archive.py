from app.services import store
import traceback

try:
    result = store.archive_old_data(days=0)
    print(f"✅ archive_old_data(0) OK: {result}")
except Exception as e:
    print(f"❌ archive_old_data 抛异常: {e}")
    traceback.print_exc()

try:
    result = store.cleanup_expired_memories(days=180)
    print(f"✅ cleanup OK: {result}")
except Exception as e:
    print(f"❌ cleanup 抛异常: {e}")
    traceback.print_exc()
