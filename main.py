import asyncio
from datetime import datetime
import json
import os

import aiohttp
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


async def send_telegram_message(chat_id, text, photo_url=None, is_gif=False):
    async with aiohttp.ClientSession() as session:
        if photo_url:
            if is_gif:
                await telegram_bot.send_animation(chat_id=chat_id, animation=photo_url, caption=text)
            else:
                async with session.get(photo_url) as resp:
                    image_data = await resp.read()
                url = f"https://api.telegram.org/bot{TELEGRAM_API_TOKEN}/sendPhoto"
                data = aiohttp.FormData()
                data.add_field("chat_id", str(chat_id))
                data.add_field("caption", text)
                data.add_field("photo", image_data, filename="photo.jpg", content_type="image/jpeg")
                await session.post(url, data=data)
        else:
            await telegram_bot.send_message(chat_id=chat_id, text=text)


def vk_upload(session, image_data, is_gif=False):
    if is_gif:
        upload_server = session.method("docs.getWallUploadServer")
        upload_url = upload_server["upload_url"]
        response = requests.post(upload_url, files={"file": ("image.gif", image_data, "image/gif")})
        result = json.loads(response.text)
        print("Ответ сервера при загрузке гифки:", result)
        try:
            docs = session.method("docs.save", {"file": result["file"], "title": "image.gif", "access": 0, "type": "gif"})
        except Exception as e:
            print(f"Ошибка при сохранении гифки в ВКонтакте: {e}")
            raise e

    else:
        upload_server = session.method("photos.getWallUploadServer")
        upload_url = upload_server["upload_url"]
        response = requests.post(upload_url, files={"photo": ("image.jpg", image_data)})
        result = json.loads(response.text)
        photos = session.method("photos.saveWallPhoto", {"photo": result["photo"], "server": result["server"], "hash": result["hash"]})
        docs = photos
    return docs[0]


def send_vk_post(owner_id, text, photo_url=None, is_gif=False):
    attachment = None
    if photo_url:
        image_data = requests.get(photo_url).content
        if is_gif:
            photo = vk_upload(vk_session, image_data, is_gif=True)
            attachment = f"doc{photo['owner_id']}_{photo['id']}_{photo.get('access_key', '')}"
        else:
            photo = vk_upload(vk_session, image_data)
            attachment = f"photo{photo['owner_id']}_{photo['id']}"

    try:
        response = vk.wall.post(owner_id=owner_id, message=text, attachments=attachment)
        print("Сообщение успешно отправлено на стену ВКонтакте.")
        print(f"Ответ сервера ВКонтакте при отправке сообщения: {response}")
    except KeyError as e:
        print(f"KeyError in send_vk_post: {e}")
        print(f"Тип исключения: {type(e)}")
        print(f"Атрибуты исключения: {dir(e)}")
        print(f"Данные исключения: {e.__dict__}")
        print(f"Отсутствующий ключ: {e.args[0]}") # добавьте эту строку для отображения ключа, вызывающего ошибку
        raise e
    except Exception as e:
        print(f"Другая ошибка в send_vk_post: {e}")
        raise e


def send_ok_post(group_id, text, photo_url=None):
    try:
        if photo_url:
            photo_id = ok_api.photo_upload(url=photo_url, gid=group_id)
        else:
            photo_id = None

        attachment = {"media": [{"type": "text", "text": text}]}

        if photo_id:
            attachment["media"].append({"type": "photo", "list": [{"id": photo_id}]})

        response = ok_api.wall_post(text="", attachments=attachment, gid=group_id)
        print(f"OK API wall_post response: {response}")

    except Exception as e:
        print(f"Ошибка при отправке сообщения в Одноклассники: {e}")
        raise e


def update_status_in_sheet(row, status_dict):
    update_range = f"I{row}:K{row}"
    body = {
        "range": update_range,
        "values": [[status_dict.get("Telegram", ""), status_dict.get("ВКонтакте", ""), status_dict.get("Одноклассники", "")]]
    }
    sheets_service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=update_range,
        valueInputOption="RAW",
        body=body
    ).execute()


async def main(last_check_time):
    await asyncio.sleep(5)
    posts = get_posts_from_sheet()

    for i, post in enumerate(posts, start=2):  # Добавьте индекс строки (начиная с 2, чтобы пропустить заголовки)
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

        status_dict = {}
        is_gif = photo_url.endswith(".gif")
        if "Telegram" in networks:
            try:
                await send_telegram_message(telegram_chat_id, text, photo_url, is_gif=is_gif)
                status_dict["Telegram"] = "Success"
            except Exception as e:
                print(f"Ошибка при отправке сообщения в Телеграм: {e}")
                status_dict["Telegram"] = f"Error: {e}"

        if "ВКонтакте" in networks:
            try:
                send_vk_post(vk_owner_id, text, photo_url, is_gif=is_gif)
                status_dict["ВКонтакте"] = "Success"
            except Exception as e:
                print(f"Ошибка при отправке сообщения в ВКонтакте: {e}")
                print(f"Тип исключения: {type(e)}")
                print(f"Атрибуты исключения: {dir(e)}")
                print(f"Данные исключения: {e.__dict__}")
                status_dict["ВКонтакте"] = f"Error: {e}"

        if "Одноклассники" in networks:
            try:
                send_ok_post(ok_group_id, text, photo_url)
                status_dict["Одноклассники"] = "Success"
            except Exception as e:
                print(f"Ошибка при отправке сообщения в Одноклассники: {e}")
                status_dict["Одноклассники"] = f"Error: {e}"

        update_status_in_sheet(posts.index(post) + 2, status_dict)

        await asyncio.sleep(60)


if __name__ == '__main__':
    while True:
        last_check_time = datetime.now()
        asyncio.run(main(last_check_time))