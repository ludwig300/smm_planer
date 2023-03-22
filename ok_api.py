import hashlib
import json

import requests


class OKAPI:
    def __init__(self, public_key, private_key, access_token):
        self.public_key = public_key
        self.private_key = private_key
        self.access_token = access_token

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

    def photo_upload(self, url):
        upload_url = self._call("photos.getUploadUrl")["upload_url"]
        response = requests.post(
            upload_url,
            files={"photo": requests.get(url).content}
        )
        photo_id = json.loads(response.text)["photo_ids"][0]
        return photo_id

    def wall_post(self, text, attachments):
        params = {"attachment": json.dumps(attachments), "message": text}
        return self._call("mediatopic.post", **params)
