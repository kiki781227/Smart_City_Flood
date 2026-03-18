from flask import Flask, jsonify, render_template, request
from serial_manager import SerialManager

app = Flask(__name__)
manager = SerialManager()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(manager.get_payload())


@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.get_json(silent=True) or {}
    cmd = (data.get("cmd") or "").strip()

    if not cmd:
        return jsonify({"ok": False, "error": "Missing command"}), 400

    result = manager.send(cmd)
    return jsonify(result)

@app.route("/api/demo/fill", methods=["POST"])
def api_demo_fill():
    manager.demo_fill()
    return jsonify({"ok": True})


if __name__ == "__main__":
    manager.start()
    app.run(host="0.0.0.0", port=5000, debug=False)