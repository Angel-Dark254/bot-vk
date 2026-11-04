import time
import requests
import vk_api
import subprocess
import sys

# --- АВТОУСТАНОВКА ---
try:
    import vk_api
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "vk_api", "requests[socks]"])

# ================= НАСТРОЙКИ =================
VK_TOKEN = "vk1.a.-3rYo_oct1ogffbBV9TSz6hFSTSMi7EetIr8KrelZw0LuPj08McUodUxzRxntOzjHdN4DC4VJxUJAFdtny88nMM6fvM58WWNO4sUjm0p8zGMEzacKApr0W219fQPGW3TlvQOtIUfUAIliN2VE78XN5cGVwOtqcH5CN4bSZDoXVdo6QeO9xFJpXJQ3_Y7Mrnql3599BroqKyghUy_p4E7KA"
VK_TARGET_USER_ID = 638956578

TG_BOT_TOKEN = "9213635740:AAGql-c8D9q6IKrR36taEZfluCQr8vT1z54"
TG_CHANNEL_ID = -1004304894570
TG_PROXY = "socks5h://VLm5KU:5T620n@68.209.60.142:8000" 

# Интервал пульса (7200 сек = 2 часа)
HEARTBEAT_INTERVAL = 7200 
# ============================================

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

def send_to_tg(text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    proxies = {"http": TG_PROXY, "https": TG_PROXY}
    try:
        response = requests.post(url, data={"chat_id": TG_CHANNEL_ID, "text": text}, timeout=15, proxies=proxies)
        if response.status_code == 200:
            print(f"✅ [ТГ] Отправлено: {text}", flush=True)
        else:
            print(f"❌ [ТГ] Ошибка API: {response.text}", flush=True)
    except Exception as e:
        print(f"❌ [ТГ] Ошибка сети: {e}", flush=True)

def get_profile_info():
    try:
        res = vk.users.get(user_ids=VK_TARGET_USER_ID, fields='online,photo_id,status,first_name,last_name')
        return res[0] if res else None
    except Exception as e:
        print(f"❌ [ВК] Ошибка API: {e}", flush=True)
        return None

def get_friends():
    try:
        res = vk.friends.get(user_id=VK_TARGET_USER_ID)
        return set(res.get('items', []))
    except:
        return set()

# --- ИНИЦИАЛИЗАЦИЯ ---
print("⏳ Загрузка初始 данных профиля ВК...", flush=True)
profile = get_profile_info()
last_online = profile.get('online') == 1 if profile else False
last_name = f"{profile.get('first_name')} {profile.get('last_name')}" if profile else ""
last_bio = profile.get('status', "") if profile else ""
last_photo_id = str(profile.get('photo_id', "")) if profile else ""
last_friends = get_friends()

print(f"👤 Начальный профиль: {last_name}, Друзей: {len(last_friends)}", flush=True)
print("🚀 VK Worker запущен (Онлайн + Профиль + Друзья + Пульс)...", flush=True)

last_friend_check = time.time()
last_heartbeat_time = time.time()

# 👇 ОТПРАВЛЯЕМ СТАРТОВЫЙ ПУЛЬС СРАЗУ ПОСЛЕ ЗАПУСКА
print("💓 [ВК] Отправляем стартовый пульс...", flush=True)
send_to_tg("VK_HEARTBEAT")

while True:
    try:
        curr_profile = get_profile_info()
        if curr_profile:
            # 1. ОНЛАЙН
            is_online = curr_profile.get('online') == 1
            if is_online and not last_online:
                send_to_tg("VK_ONLINE")
                last_online = True
            elif not is_online and last_online:
                send_to_tg("VK_OFFLINE")
                last_online = False
                
            # 2. ИМЯ
            curr_name = f"{curr_profile.get('first_name')} {curr_profile.get('last_name')}"
            if curr_name != last_name and last_name != "":
                send_to_tg(f"🔄 Изменения в ВК!\n\n👤 Имя: {last_name} ➡️ {curr_name}")
                last_name = curr_name
                
            # 3. БИО
            curr_bio = curr_profile.get('status', "")
            if curr_bio != last_bio and last_bio != "":
                b_old = last_bio if last_bio else "пусто"
                b_new = curr_bio if curr_bio else "пусто"
                send_to_tg(f"🔄 Изменения в ВК!\n\n📝 Био/Статус:\n{b_old} ➡️ {b_new}")
                last_bio = curr_bio
                
            # 4. АВАТАРКА
            curr_photo_id = str(curr_profile.get('photo_id', ""))
            if curr_photo_id != last_photo_id and last_photo_id != "":
                send_to_tg(f"🔄 Изменения в ВК!\n\n🖼 Пользователь сменил аватарку!")
                last_photo_id = curr_photo_id

        # 5. ДРУЗЬЯ (раз в 2 минуты)
        if time.time() - last_friend_check > 120:
            current_friends = get_friends()
            if current_friends:
                added = current_friends - last_friends
                removed = last_friends - current_friends
                
                if added:
                    users_info = vk.users.get(user_ids=",".join(map(str, list(added))))
                    for u in users_info:
                        send_to_tg(f"🔄 Изменения в ВК!\n\n🟢 Новый друг: {u['first_name']} {u['last_name']}")
                
                if removed:
                    try:
                        users_info = vk.users.get(user_ids=",".join(map(str, list(removed))))
                        for u in users_info:
                            send_to_tg(f"🔄 Изменения в ВК!\n\n🔴 Удален из друзей: {u['first_name']} {u['last_name']}")
                    except:
                        send_to_tg(f"🔄 Изменения в ВК!\n\n🔴 Удалено из друзей: {len(removed)} чел.")
                
                last_friends = current_friends
            last_friend_check = time.time()

        # 6. ПУЛЬС (раз в 2 часа)
        if time.time() - last_heartbeat_time > HEARTBEAT_INTERVAL:
            print("💓 [ВК] Отправляем плановый пульс...", flush=True)
            send_to_tg("VK_HEARTBEAT")
            last_heartbeat_time = time.time()

    except Exception as e:
        print(f"❌ Ошибка ВК: {e}", flush=True)
        
    time.sleep(10)
