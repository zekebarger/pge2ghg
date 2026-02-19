import requests
from requests.auth import HTTPBasicAuth
import yaml

import pandas as pd

def read_secrets():
    with open('./secrets.yaml', 'r') as f:
        data = yaml.load(f, Loader=yaml.SafeLoader)
    return data["secrets"]

def login():
    secrets = read_secrets()
    login_url = 'https://api.watttime.org/login'
    rsp = requests.get(login_url, auth=HTTPBasicAuth(secrets["name"], secrets["pass"]))
    return rsp.json()['token']

def get_historical(start, end):
    token = login()
    # tokens expire after 30 minutes
    # making a request with an expired token will produce a  401 error

    url = "https://api.watttime.org/v3/historical"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "region": "CAISO_NORTH",
        "start": start, #"2025-01-01T00:00+00:00",
        "end": end, #"2025-02-01T00:05+00:00",
        "signal_type": "co2_moer",
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    df = pd.DataFrame.from_dict(response.json()["data"])
    return df