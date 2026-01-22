import os

os.environ.setdefault('BOT_ROLE', 'paper')
os.environ.setdefault('BOT_ID', 'paper-1')
os.environ.setdefault('BOT_VERSION', '1.0.0')

from main import main

if __name__ == '__main__':
    main()
