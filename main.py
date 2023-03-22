import asyncio
from datetime import datetime
import json
import os
from time import sleep

import requests
import vk_api
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from telegram import Bot

from ok_api import OKAPI

load_dotenv()

# Загрузка переменных окружения
GOOGLE_API_CREDENTIALS = os.getenv("GOOGLE_API_CREDENTIALS")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
VK_ACCESS_TOKEN = os.getenv("VK_ACCESS_TOKEN")
TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
OK_ACCESS_TOKEN = os.getenv("OK_ACCESS_TOKEN")
OK_PUBLIC_KEY = os.getenv("OK_PUBLIC_KEY")
OK_PRIVATE_KEY = os.getenv("OK_PRIVATE_KEY")

# Аутентификация и создание клиента Google Sheets API
credentials = service_account.Credentials.from_service_account_file(
    GOOGLE_API_CREDENTIALS,
    scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents.readonly"]
)
sheets_service = build("sheets", "v4", credentials=credentials)

# Аутентификация и создание клиента Telegram Bot API
telegram_bot = Bot(token=TELEGRAM_API_TOKEN)

# Аутентификация и создание клиента VK API
vk_session = vk_api.VkApi(token=VK_ACCESS_TOKEN)
vk = vk_session.get_api()

# Аутентификация и создание клиента OK API
ok_api = OKAPI(access_token=OK_ACCESS_TOKEN, public_key=OK_PUBLIC_KEY, private_key=OK_PRIVATE_KEY)


def get_posts_from_sheet():
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="A2:H"
    ).execute()
    return result.get("values", [])


def process_google_doc(doc_id):
    docs_service = build("docs", "v1", credentials=credentials)
    doc = docs_service.documents().get(documentId=doc_id).execute()
    return doc.get("body", {}).get("content", [])


async def send_telegram_message(chat_id, text, photo_url=None):
    if photo_url:
        await telegram_bot.send_photo(chat_id=chat_id, photo=photo_url, caption=text)
    else:
        await telegram_bot.send_message(chat_id=chat_id, text=text)


def send_vk_post(owner_id, text, photo_url=None):
    if photo_url:
        image_data = requests.get(photo_url).content
        photo = vk_upload(vk_session, image_data)
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
    else:
        attachment = None

    vk.wall.post(owner_id=owner_id, message=text, attachments=attachment)


def vk_upload(session, image_data):
    upload_server = session.method("photos.getWallUploadServer")
    upload_url = upload_server["upload_url"]
    response = requests.post(upload_url, files={"photo": ("image.jpg", image_data)})
    result = json.loads(response.text)
    photos = session.method("photos.saveWallPhoto", {"photo": result["photo"], "server": result["server"], "hash": result["hash"]})
    return photos[0]


def send_ok_post(text, photo_url=None):
    if photo_url:
        image_data = requests.get(photo_url).content
        photo_id = ok_api.photo_upload(image_data)
    else:
        photo_id = None

    ok_api.post(text, photo_id)


async def main(last_check_time):
    posts = get_posts_from_sheet()

    for post in posts:
        post_date, post_time, networks, doc_url, photo_url, telegram_chat_id, vk_owner_id, ok_group_id = post
        post_datetime_str = f"{post_date} {post_time}"
        post_datetime = datetime.strptime(post_datetime_str, "%d.%m.%Y %H:%M")
        now = datetime.now()

        # Проверяем, отправлялись ли сообщения в прошлый раз
        if post_datetime <= last_check_time:
            continue

        # Вычисляем задержку
        delay = (post_datetime - now).total_seconds()
        if delay > 0:
            # Ожидаем задержку
            await asyncio.sleep(delay)

        # Продолжаем с отправкой сообщений
        text = ""
        doc_id = doc_url.split("/")[-1]
        doc_content = process_google_doc(doc_id)
        for item in doc_content:
            if "paragraph" in item:
                for element in item["paragraph"]["elements"]:
                    if "textRun" in element:
                        text += element["textRun"]["content"]

        if "Telegram" in networks:
            try:
                await send_telegram_message(telegram_chat_id, text, photo_url)
            except Exception as e:
                print(f"Ошибка при отправке сообщения в Телеграм: {e}")

        if "ВКонтакте" in networks:
            try:
                send_vk_post(vk_owner_id, text, photo_url)
            except Exception as e:
                print(f"Ошибка при отправке сообщения в ВКонтакте: {e}")

        if "ok" in networks:
            try:
                send_ok_post(ok_group_id, text, photo_url)
            except Exception as e:
                print(f"Ошибка при отправке сообщения в Одноклассники: {e}")


if __name__ == '__main__':
    last_check_time = datetime.now()
    while True:
        asyncio.run(main(last_check_time))
        last_check_time = datetime.now()
        sleep(60)
