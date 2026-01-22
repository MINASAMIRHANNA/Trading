import os

os.environ.setdefault('BOT_ROLE', 'live')
os.environ.setdefault('BOT_ID', 'live-1')
os.environ.setdefault('BOT_VERSION', '1.0.0')

from main import main

if __name__ == '__main__':
    main()
