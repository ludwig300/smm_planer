import hashlib
import json

import requests


class OKAPI:
    def __init__(self, access_token, public_key, private_key, gid=None, aid=None):
        self.access_token = access_token
        self.public_key = public_key
        self.private_key = private_key
        self.gid = gid
        self.aid = aid

    def _sig(self, params):
        sorted_params = "".join(
            k + "=" + str(params[k]) for k in sorted(params.keys())
        )
        return hashlib.md5(
            (sorted_params + self.private_key).encode("utf-8")
        ).hexdigest()

    def _call(self, method, **params):
        params["application_key"] = self.public_key
        params["method"] = method
        params["format"] = "json"
        params["sig"] = self._sig(params)
        params["access_token"] = self.access_token
        response = requests.post("https://api.ok.ru/fb.do", data=params)
        response.raise_for_status()
        return response.json()

    def get_photo_upload_url(self):
        return self._call("photos.getUploadUrl")["upload_url"]

    def _get_photo_upload_server(self):
        method = "photosV2.getUploadUrl"
        params = {
            "gid": self.gid,
            "aid": self.aid,
        }
        return self._call(method, **params)

    def photo_upload(self, url):
        try:
            resp = self._get_photo_upload_server()
            upload_url = resp["upload_url"]
        except KeyError:
            print(f"Ошибка: Ответ сервера: {resp}")
            return None

        response = requests.get(url)
        photo_data = response.content

        files = {"pic1": ("photo.jpg", photo_data, "image/jpeg")}
        response = requests.post(upload_url, files=files)
        result = response.json()

        photo_id = result["photo_ids"][0]
        return photo_id