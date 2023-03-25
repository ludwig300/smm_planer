import requests

client_id = 'YOUR_CLIENT_ID'
client_secret = 'YOUR_CLIENT_SECRET'
redirect_uri = 'https://localhost'
authorization_code = 'YOUR_AUTHORIZATION_CODE'

url = 'https://api.ok.ru/oauth/token.do'

data = {
    'code': authorization_code,
    'client_id': client_id,
    'client_secret': client_secret,
    'redirect_uri': redirect_uri,
    'grant_type': 'authorization_code'
}

response = requests.post(url, data=data)
response_json = response.json()
access_token = response_json['access_token']