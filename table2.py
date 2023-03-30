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
            response = await telegram_bot.send_photo(chat_id=chat_id, photo=image_data, caption=text)
            return response['message_id']
        else:
            response = await telegram_bot.send_message(chat_id=chat_id, text=text)
            return response['message_id']


def send_vk_post(owner_id, text, photo_url=None):
    if photo_url:
        image_data = requests.get(photo_url).content
        photo = vk_upload(vk_session, image_data)
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
    else:
        attachment = None
    response = vk.wall.post(owner_id=owner_id, message=text, attachments=attachment)
    if '-' in response:
        return f'https://vk.com/wall{owner_id}?own=1&{owner_id}_{response["post_id"]}'
    else:
        return f'https://vk.com/wall{owner_id}_{response["post_id"]}'


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


def update_status_in_sheet(status_dict, names, rows=(1, 1), colons=('I', 'K'), sheet='', text="Pass"):
    if status_dict:
        row_start, row_end = rows
        colon_start, colon_end = colons
        update_range = f"{colon_start}{row_start}:{colon_end}{row_end}"
        if sheet:
            update_range = f"'{sheet}'!{update_range}"
        values = []
        for name in names:
            values.append(status_dict.get(name, text))
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


def status_log_row_check(log, row, check_name):
    if not log:
        return False
    try:
        log = log[row]
    except IndexError:
        return False
    for colon in log:
        if not colon:
            continue
        cell = colon.split(', ')
        try:
            name, status = cell
            if name == check_name:
                return status
        except ValueError:
            continue

    return False


async def main(last_check_time):
    await asyncio.sleep(5)
    networks = get_posts_from_sheet("Соцсети!A3:E9")  # содержимое заданного листа по точным координатам
    networks_log = get_posts_from_sheet("log!A:G")
    names = {}
    network_ids = []
    for i, network in enumerate(networks):
        try:
            name, network_type, name_id = network
        except ValueError:
            continue
        names[name] = network_type, name_id
        network_ids.append(name_id)
    posts = get_posts_from_sheet("requests log!E:A3")
    posts = posts[::-1]
    row = len(posts) + 2
    row_check = len(posts) + 1
    for i, post in enumerate(posts):
        try:
            post_date, post_time, doc_url, photo_url, check_names = post
        except ValueError:
            row_check -= 1
            row -= 1
            continue
        if not all([post_date, post_time, check_names]) and not any([doc_url, photo_url]):
            row_check -= 1
            row -= 1
            continue
        if not any([doc_url, photo_url]):
            row_check -= 1
            row -= 1
            continue
        check_names = check_names.split(', ')
        post_datetime_str = f"{post_date} {post_time}"
        try:
            post_datetime = datetime.strptime(post_datetime_str, "%d.%m.%Y %H:%M")
        except ValueError:
            row_check -= 1
            row -= 1
            continue

        now = datetime.now()
        # Проверяем время отправки
        if post_datetime > now:
            row_check -= 1
            row -= 1
            continue

        text = ""
        if doc_url:
            doc_id = doc_url.split("/")[-1]
            doc_content = process_google_doc(doc_id)
            for item in doc_content:
                if "paragraph" in item:
                    for element in item["paragraph"]["elements"]:
                        if "textRun" in element:
                            text += element["textRun"]["content"]

        status_dict = {}
        links = {}
        log = {}
        for name in check_names:
            network, network_id = names.get(name)
            if network == 'TG' and not status_log_row_check(networks_log, row_check, network_id):
                try:
                    await asyncio.sleep(6)
                    link = await send_telegram_message(network_id, text, photo_url)
                    status_dict[network_id] = "Success"
                    links[network_id] = f'https://tlgg.ru/{network_id}/{link}'
                    log[network_id] = f'{network_id}, True'
                    print('Send', row)

                except Exception as e:
                    print(f"Ошибка при отправке сообщения в Телеграм: {e}")
                    status_dict[network_id] = f"Error: {e}"
                    log[network_id] = f'{network_id}, False'

            if network == 'VK' and not status_log_row_check(networks_log, row_check, network_id):
                try:
                    link = send_vk_post(network_id, text, photo_url)
                    status_dict[network_id] = "Success"
                    links[network_id] = link
                    log[network_id] = f'{network_id}, True'
                except Exception as e:
                    print(f"Ошибка при отправке сообщения в ВКонтакте: {e}")
                    status_dict[network_id] = f"Error: {e}"
                    log[network_id] = f'{network_id}, False'

            if network == 'OK' and not status_log_row_check(networks_log, row_check, network_id):
                try:
                    link = send_ok_post(network_id, text, photo_url)
                    status_dict[network_id] = "Success"
                    links[network_id] = link
                    log[network_id] = f'{network_id}, True'
                except Exception as e:
                    print(f"Ошибка при отправке сообщения в Одноклассники: {e}")
                    log[network_id] = f'{network_id}, False'
                    status_dict[network_id] = f"Error: {e}"

        update_status_in_sheet(status_dict, network_ids, colons=('F', 'L'), rows=(row, row), sheet='requests log')
        update_status_in_sheet(links, network_ids, colons=('M', 'S'), rows=(row, row), sheet='requests log')
        # print(log, row) 
        update_status_in_sheet(log, network_ids, colons=('A', 'G'), rows=(row, row), sheet='log')
        row_check -= 1
        row -= 1


#
if __name__ == '__main__':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    while True:
        last_check_time = datetime.now()
        asyncio.run(main(last_check_time))
