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
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents.readonly",
        ]
)
sheets_service = build("sheets", "v4", credentials=credentials)

# Аутентификация и создание клиента Telegram Bot API
telegram_bot = Bot(token=TELEGRAM_API_TOKEN)

# Аутентификация и создание клиента VK API
vk_session = vk_api.VkApi(token=VK_ACCESS_TOKEN)
vk = vk_session.get_api()

# Аутентификация и создание клиента OK API
ok_api = OKAPI(access_token=OK_ACCESS_TOKEN, public_key=OK_PUBLIC_KEY, private_key=OK_PRIVATE_KEY)

def get_posts_from_sheet(range="A2:H"):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=range
    ).execute()
    return result.get("values", [])


def process_google_doc(doc_id):
    docs_service = build("docs", "v1", credentials=credentials)
    doc = docs_service.documents().get(documentId=doc_id).execute()
    return doc.get("body", {}).get("content", [])


async def send_telegram_message(chat_id, text, photo_url=None):
    async with aiohttp.ClientSession() as session:
        if photo_url:
            async with session.get(photo_url) as resp:
                image_data = await resp.read()
            await telegram_bot.send_photo(chat_id=chat_id, photo=image_data, caption=text)
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
        if type(response) == 'dict':
            response.get('error_code')
            raise Exception(f'code status {response["error_code"]}')
        return f'https://ok.ru/group/{group_id}/topic/{response}'

    except Exception as e:
        print(f"Ошибка при отправке сообщения в Одноклассники: {e}")
        raise e


def update_status_in_sheet(status_dict, names, rows=(1, 1), colons=('I', 'K'), sheet=''):
    row_start, row_end = rows
    colon_start, colon_end = colons
    update_range = f"{colon_start}{row_start}:{colon_end}{row_end}"
    if sheet:
        update_range = f"'{sheet}'!{update_range}"
    values = []
    for name in names:
        values.append(status_dict.get(name, "Pass"))
    body = {
        "range": update_range,
        "values": [values]
    }
    sheets_service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=update_range,
        valueInputOption="RAW",
        body=body
    ).execute()



async def main(last_check_time):
    await asyncio.sleep(5)
    networks = get_posts_from_sheet("БД \"Соцсети\"!A3:E7")  # содержимое заданного листа по точным координатам
    names = {}
    network_ids = []
    for i, network in enumerate(networks):
        name, network_type, name_id = network
        names[name] = network_type, name_id
        network_ids.append(name_id)
    posts = get_posts_from_sheet("requests log!E:A3")
    posts = posts[::-1]
    row = len(posts) + 2
    for i, post in enumerate(posts):
        post_date, post_time, doc_url, photo_url, check_names = post
        if not post_date or not post_time:
            row -= 1
            continue
        check_names = check_names.split(', ')
        post_datetime_str = f"{post_date} {post_time}"
        post_datetime = datetime.strptime(post_datetime_str, "%d.%m.%Y %H:%M")
        now = datetime.now()
        # Проверяем, отправлялись ли сообщения в прошлый раз
        if post_datetime <= last_check_time:
            row -= 1
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
        links = {}


        for name in check_names:
            network, network_id = names[name]
            if network == 'TG':
                try:
                    await send_telegram_message(network_id, text, photo_url)
                    status_dict[network_id] = "Success"
                    links[network_id] = f'https://t.me/{network_id}'

                except Exception as e:
                    print(f"Ошибка при отправке сообщения в Телеграм: {e}")
                    status_dict[network_id] = f"Error: {e}"

            if network == 'VK':
                try:
                    send_vk_post(network_id, text, photo_url)
                    status_dict[network_id] = "Success"
                    links[network_id] = f'https://vk.com/id{network_id}'
                except Exception as e:
                    print(f"Ошибка при отправке сообщения в ВКонтакте: {e}")
                    status_dict[network_id] = f"Error: {e}"

            if network == 'OK':
                try:
                    link = send_ok_post(network_id, text, photo_url)
                    status_dict[network_id] = "Success"
                    links[network_id]= link
                except Exception as e:
                    print(f"Ошибка при отправке сообщения в Одноклассники: {e}")
                    status_dict[network_id] = f"Error: {e}"
        update_status_in_sheet(status_dict, network_ids, colons=('F', 'L'), rows=(row, row), sheet='requests log')
        update_status_in_sheet(links, network_ids, colons=('M', 'S'), rows=(row, row), sheet='requests log')
        # Ссылка на группу или канал, а не на пост
        row -= 1

    await asyncio.sleep(60)

if __name__ == '__main__':
    last_check_time = datetime.now()
    while True:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main(last_check_time))
        last_check_time = datetime.now()

