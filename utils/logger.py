import logging
from logging.handlers import RotatingFileHandler
import sys
import os

# Создаем директорию для логов, если её нет
if not os.path.exists('logs'):
    os.makedirs('logs')

# Настраиваем основной логгер
def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Устанавливаем уровень логирования

    # Форматтер для логов
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Хендлер для записи в файл
    file_handler = RotatingFileHandler(
        filename='logs/bot.log',
        maxBytes=5242880,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Хендлер для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Добавляем хендлеры к логгеру
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger 