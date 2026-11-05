import sys, json; sys.path.insert(0, r"D:\code\inspectagent-cloud")
from app.agent import tools

print("🛠 新工具调用测试")
print("=" * 50)

print("📸 ask_user_reshoot:")
r = tools.dispatch("ask_user_reshoot", {"reason": "图像过曝看不清指针", "suggestion": "关灯后正面拍"})
print(f"  {json.loads(r)['message'][:80]}...")

print("👥 get_contacts:")
r = tools.dispatch("get_contacts", {"deviceId": "D-3001", "area": "A区"})
d = json.loads(r)
print(f"  负责人: {d['contacts']['primary']['name']} / {d['contacts']['primary']['phone']}")

print("🔧 similar_devices:")
r = tools.dispatch("similar_devices", {"deviceType": "低压配电柜", "excludeDeviceId": "D-3001"})
d = json.loads(r)
print(f"  同类型设备: {d['count']} 台")

print("\n✅ 所有新工具 OK")
print(f"\ntools.TOOLS 总数: {len(tools.TOOLS)}")
for t in tools.TOOLS:
    print(f"  🛠 {t['function']['name']} - {t['function']['description'][:40]}")
