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

    def photo_upload(self, url, gid=None):
        if gid is not None:
            self.gid = gid

        try:
            resp = self._get_photo_upload_server()
            upload_url = resp["upload_url"]
        except KeyError:
            print(f"Ошибка: Ответ сервера: {resp}")
            return None

        response = requests.get(url)
        photo_data = response.content

        # Измените эту строку, чтобы определить тип файла на основе URL
        file_extension = url.split(".")[-1]
        content_type = f"image/{file_extension}"

        files = {"pic1": (f"photo.{file_extension}", photo_data, content_type)}
        response = requests.post(upload_url, files=files)
        result = response.json()
        photo_info = list(result["photos"].values())[0]
        photo_id = photo_info["token"]

        return photo_id


    def wall_post(self, text, attachments, gid=None, uid=None):
        if gid is None and uid is None:
            raise ValueError("Either 'gid' or 'uid' should be provided.")
        params = {
            "attachment": json.dumps(attachments),
            "type": "GROUP_THEME" if gid else "USER_THEME",
        }

        if gid:
            params["gid"] = gid
        elif uid:
            params["uid"] = uid

        if text:
            params["message"] = text

        response = self._call("mediatopic.post", **params)
        return response
