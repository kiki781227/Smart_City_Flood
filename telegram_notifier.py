import requests


class TelegramNotifier:
    def __init__(self, token="", chat_id="", enabled=True):
        self.token = (token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.enabled = enabled

    def is_configured(self):
        return self.enabled and bool(self.token) and bool(self.chat_id)

    def send(self, text: str):
        if not self.enabled:
            return {"ok": False, "disabled": True, "error": "Telegram disabled"}

        if not self.token or not self.chat_id:
            return {"ok": False, "disabled": True, "error": "Missing token or chat_id"}

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
        }

        try:
            r = requests.post(url, json=payload, timeout=8)

            try:
                data = r.json()
            except Exception:
                return {"ok": False, "error": f"Non-JSON response: {r.text}"}

            if r.status_code == 200 and data.get("ok") is True:
                return {"ok": True}

            return {"ok": False, "error": data.get("description", f"HTTP {r.status_code}")}

        except Exception as e:
            return {"ok": False, "error": str(e)}