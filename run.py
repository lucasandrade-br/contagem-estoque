import os
from app import create_app
from config import Config

app = create_app(Config)

if __name__ == '__main__':
    app.run(debug=Config.DEBUG, host=Config.HOST, port=Config.PORT)
