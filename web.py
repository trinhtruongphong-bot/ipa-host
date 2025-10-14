from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "<h2>🤖 IPA Bot is running on Render Free Web Service!</h2>"

def run_bot():
    os.system("python bot.py")

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=10000)
