import socket
import os
import sys
import zipfile
import argparse
import threading
import questionary
from tqdm import tqdm

# --- НОВОЕ: Импорт для GUI выбора файлов ---
import tkinter as tk
from tkinter import filedialog

# --- Ключевые константы ---
BUFFER_SIZE = 1024 * 1024  # 1MB
TCP_PORT = 5001
UDP_PORT = 5002
SEPARATOR = "<SEP>"

# --- Общие компоненты ---

def get_local_ip():
    """Получает локальный IP-адрес для отображения пользователю."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def zip_directory(path, zip_handler):
    """Рекурсивно упаковывает директорию в ZIP-архив."""
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            arcname = os.path.relpath(file_path, os.path.dirname(path))
            zip_handler.write(file_path, arcname)

# --- НОВАЯ ФУНКЦИЯ: GUI для выбора файлов ---
def select_files_gui():
    """
    Открывает графический интерфейс для выбора файлов или папок.
    Возвращает список путей.
    """
    # Создаем и сразу прячем главное окно Tkinter, нам нужно только диалоговое
    root = tk.Tk()
    root.withdraw()

    # Спрашиваем пользователя, что именно он хочет выбрать
    selection_type = questionary.select(
        "Что вы хотите отправить?",
        choices=["📄 Отдельные файлы", "📁 Целую папку", "❌ Отмена"]
    ).ask()

    if selection_type is None or selection_type == "❌ Отмена":
        return []

    if selection_type == "📄 Отдельные файлы":
        # Открываем диалог для выбора НЕСКОЛЬКИХ файлов
        # askopenfilenames возвращает кортеж путей, преобразуем его в список
        filepaths = filedialog.askopenfilenames(title="Выберите файлы для отправки")
        return list(filepaths)
    
    elif selection_type == "📁 Целую папку":
        # Открываем диалог для выбора ОДНОЙ папки
        folderpath = filedialog.askdirectory(title="Выберите папку для отправки")
        # Возвращаем путь в виде списка, чтобы унифицировать обработку
        return [folderpath] if folderpath else []
    
    return []

# --- Режим сервера (отправка) ---

def send_files(filepaths):
    """Запускает сервер для отправки выбранных файлов и папок."""
    files_to_send = []
    temp_zip_files = []

    for path in filepaths:
        if not os.path.exists(path):
            print(f"❌ Ошибка: Путь '{path}' не существует. Он будет пропущен.")
            continue
        if os.path.isdir(path):
            print(f"🗜️  Упаковка папки '{os.path.basename(path)}' в ZIP...")
            zip_name = f"{os.path.basename(path)}.zip"
            with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zip_directory(path, zipf)
            files_to_send.append(zip_name)
            temp_zip_files.append(zip_name)
        else:
            files_to_send.append(path)

    if not files_to_send:
        print("🔴 Нет файлов для отправки.")
        return

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('0.0.0.0', TCP_PORT))
    except OSError:
        print(f"🔴 Ошибка: Порт {TCP_PORT} уже используется. Завершение.")
        return
        
    s.listen(1)
    
    local_ip = get_local_ip()
    print("\n✅ Сервер запущен!")
    print(f"🖥️  Ваш IP-адрес: {local_ip}")
    print(f"🔒 Порт: {TCP_PORT}")
    print("⏳ Ожидание подключения клиента...")

    try:
        client_socket, address = s.accept()
        print(f"🤝 Установлено соединение с {address}")

        for filename in files_to_send:
            filesize = os.path.getsize(filename)
            print(f"\n📤 Отправка файла: {os.path.basename(filename)} ({filesize / 1e6:.2f} MB)")
            client_socket.send(f"{os.path.basename(filename)}{SEPARATOR}{filesize}".encode())

            progress = tqdm(range(filesize), f"Отправка {os.path.basename(filename)}", unit="B", unit_scale=True, unit_divisor=1024)
            with open(filename, "rb") as f:
                while True:
                    bytes_read = f.read(BUFFER_SIZE)
                    if not bytes_read:
                        break
                    client_socket.sendall(bytes_read)
                    progress.update(len(bytes_read))
            progress.close()

    except Exception as e:
        print(f"❌ Произошла ошибка: {e}")
    finally:
        print("\n🔌 Закрытие соединений...")
        s.close()
        for zip_file in temp_zip_files:
            if os.path.exists(zip_file):
                os.remove(zip_file)
                print(f"🗑️  Удален временный файл: {zip_file}")
        print("✅ Готово!")

# --- Режим клиента (получение) ---

def receive_files():
    """Запускает клиент для получения файлов."""
    server_ip = questionary.text(
        "✏️ Введите IP-адрес отправителя:",
        validate=lambda text: True if len(text.split('.')) == 4 else "Неверный формат IP (например, 192.168.1.5)"
    ).ask()

    if not server_ip:
        return

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        print(f"⏳ Подключение к {server_ip}:{TCP_PORT}...")
        s.connect((server_ip, TCP_PORT))
        print("✅ Успешно подключено!")

        while True:
            received = s.recv(BUFFER_SIZE).decode()
            if not received:
                break

            try:
                filename, filesize = received.split(SEPARATOR)
                filename = os.path.basename(filename)
                filesize = int(filesize)
            except ValueError:
                print("🔴 Ошибка: получены некорректные метаданные.")
                continue

            print(f"\n📥 Получение файла: {filename} ({filesize / 1e6:.2f} MB)")
            
            progress = tqdm(range(filesize), f"Получение {filename}", unit="B", unit_scale=True, unit_divisor=1024)
            with open(filename, "wb") as f:
                bytes_received = 0
                while bytes_received < filesize:
                    bytes_to_read = min(BUFFER_SIZE, filesize - bytes_received)
                    bytes_read = s.recv(bytes_to_read)
                    if not bytes_read:
                        break
                    f.write(bytes_read)
                    progress.update(len(bytes_read))
                    bytes_received += len(bytes_read)
            progress.close()

            if filename.endswith('.zip'):
                print(f"🤐 Распаковка архива {filename}...")
                try:
                    with zipfile.ZipFile(filename, 'r') as zip_ref:
                        zip_ref.extractall()
                    os.remove(filename)
                    print(f"🗑️  Архив '{filename}' удален.")
                except zipfile.BadZipFile:
                    print(f"⚠️ Не удалось распаковать {filename}. Возможно, файл поврежден.")

    except socket.error as e:
        print(f"❌ Ошибка подключения: {e}")
    finally:
        s.close()
        print("\n✅ Работа завершена.")

# --- Главное меню и запуск ---

def main():
    """Главная функция, отображающая меню и обрабатывающая аргументы."""
    parser = argparse.ArgumentParser(description="🚀 Fast File Transfer - быстрая передача файлов по локальной сети.")
    parser.add_argument("-s", "--send", nargs='+', help="Режим отправки. Укажите пути к файлам/папкам.")
    
    args = parser.parse_args()

    if args.send:
        send_files(args.send)
        return

    print("╔══════════════════════════════╗")
    print("║    🚀 Fast File Transfer     ║")
    print("╚══════════════════════════════╝")

    choice = questionary.select(
        "Выберите режим работы:",
        choices=[
            '📤 Отправить файлы',
            '📥 Получить файлы',
            '🚪 Выход'
        ]
    ).ask()

    if choice == '📤 Отправить файлы':
        # --- ИЗМЕНЕНИЕ: Заменяем текстовый ввод на GUI ---
        selected_paths = select_files_gui()
        if selected_paths:
            send_files(selected_paths)
        else:
            print("🤷 Выбор отменен. Возврат в главное меню.")

    elif choice == '📥 Получить файлы':
        receive_files()
    elif choice == '🚪 Выход' or choice is None:
        print("До свидания! 👋")
        sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, TypeError):
        print("\nВыход из программы. 👋")
        sys.exit(0)