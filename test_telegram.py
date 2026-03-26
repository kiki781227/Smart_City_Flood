import requests

TOKEN = "8557381776:AAFXl7OCoIRbb2EKecmVeqK3wgSfg9F6xug"
CHAT_ID = "8746700326"

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "Test direct depuis Python",
}

try:
    r = requests.post(url, json=payload, timeout=8)
    print("STATUS =", r.status_code)
    print("TEXT =", r.text)
except Exception as e:
    print("EXCEPTION =", e)