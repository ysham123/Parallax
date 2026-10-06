"""Disposable Docker smoke test; no provider credentials or inference."""
import json
import secrets
import subprocess
import time
import urllib.request
import urllib.error

token=secrets.token_urlsafe(48)
container=None
try:
    container=subprocess.check_output(["docker","run","--rm","-d","-p","127.0.0.1::8080",
        "-e","PARALLAX_ACCESS_TOKEN="+token,"-e","PARALLAX_STUDIO_ORIGINS=https://studio.example.com",
        "-e","PARALLAX_ALLOWED_HOSTS=runtime.example.com","parallax-runtime"],text=True).strip()
    address=subprocess.check_output(["docker","port",container,"8080"],text=True).strip()
    url="http://"+address
    for attempt in range(50):
        try:
            with urllib.request.urlopen(url+"/api/health",timeout=2) as response:
                assert json.load(response)["ok"]
            break
        except (OSError,urllib.error.URLError): time.sleep(.2)
    else: raise RuntimeError("Container did not become healthy")
    request=urllib.request.Request(url+"/api/runs")
    try:
        urllib.request.urlopen(request,timeout=5)
        raise AssertionError("Unauthenticated runtime exposed private runs")
    except urllib.error.HTTPError as error: assert error.code==401
    request=urllib.request.Request(url+"/api/runs",headers={"Authorization":"Bearer "+token})
    with urllib.request.urlopen(request,timeout=5) as response: assert json.load(response)==[]
    request=urllib.request.Request(url+"/api/health",headers={"Host":"healthcheck.railway.app"})
    with urllib.request.urlopen(request,timeout=5) as response: assert json.load(response)["ok"]
    print("Railway container health and authentication passed.")
finally:
    if container: subprocess.run(["docker","stop",container],check=True,stdout=subprocess.DEVNULL)
