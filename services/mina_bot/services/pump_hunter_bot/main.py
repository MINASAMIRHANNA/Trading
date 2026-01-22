import os

os.environ.setdefault('BOT_ROLE', 'pump')
os.environ.setdefault('BOT_ID', 'pump-1')
os.environ.setdefault('BOT_VERSION', '1.0.0')

import pump_hunter

if __name__ == '__main__':
    pump_hunter.main()
