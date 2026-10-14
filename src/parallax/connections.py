"""Connection metadata and OS credentials, separate from durable run records."""
from __future__ import annotations
import ctypes
import json
import os
import re
import sys
import uuid
from urllib.parse import urlsplit
from pydantic import Field, SecretStr, field_validator
from .models import Contract, Participant

NATIVE = ("codex", "claude", "grok", "antigravity")
DEFAULTS = {
    "codex": ("responses", "https://api.openai.com/v1", "gpt-6.1-sol"),
    "claude": ("anthropic", "https://api.anthropic.com/v1", "claude-sonnet-5-5"),
    "grok": ("responses", "https://api.x.ai/v1", "grok-4.7"),
    "antigravity": ("openai", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash"),
}

class ModelCapability(Contract):
    id: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=200)
    efforts: list[str] = Field(default_factory=list, max_length=20)
    @field_validator("efforts")
    @classmethod
    def explicit_efforts(cls, values):
        if len(set(values)) != len(values) or any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", v) for v in values):
            raise ValueError("Efforts require unique, explicit API values")
        return values

class ConnectionInput(Contract):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    name: str | None = Field(default=None, max_length=100)
    protocol: str | None = Field(default=None, max_length=30)
    endpoint: str | None = Field(default=None, max_length=2048)
    api_key: SecretStr | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    models: list[ModelCapability] | None = Field(default=None, max_length=5000)
    default_model: str | None = Field(default=None, min_length=1, max_length=200)

class CredentialVault:
    """macOS Keychain; other platforms use an explicitly named environment variable."""
    storage = "macOS Keychain" if sys.platform == "darwin" else "environment reference"
    def __init__(self):
        self.service = b"Parallax API connections"
        self.lib = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security") if sys.platform == "darwin" else None
        if self.lib:
            self.lib.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p)]
            self.lib.SecKeychainAddGenericPassword.argtypes = [ctypes.c_void_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)]
            self.lib.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_char_p]
            self.lib.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
            self.lib.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p,ctypes.c_void_p]
            self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            self.cf.CFRelease.argtypes = [ctypes.c_void_p]
    def _find(self, identifier):
        account=identifier.encode();length=ctypes.c_uint32();data=ctypes.c_void_p();item=ctypes.c_void_p()
        status=self.lib.SecKeychainFindGenericPassword(None,len(self.service),self.service,len(account),account,ctypes.byref(length),ctypes.byref(data),ctypes.byref(item))
        if status == -25300: return None,None
        if status: raise ValueError(f"Keychain access failed ({status}); use an environment reference if unavailable")
        try: value=ctypes.string_at(data,length.value).decode()
        finally: self.lib.SecKeychainItemFreeContent(None,data)
        return value,item
    def get(self, identifier, env=None):
        if env: return os.environ.get(env)
        if not self.lib: return None
        value,item=self._find(identifier)
        if item: self.cf.CFRelease(item)
        return value
    def set(self, identifier, value):
        if not self.lib: raise ValueError("On this platform, configure api_key_env instead of storing a key")
        _,item=self._find(identifier);raw=value.encode();account=identifier.encode()
        try:
            if item: status=self.lib.SecKeychainItemModifyAttributesAndData(item,None,len(raw),raw)
            else: status=self.lib.SecKeychainAddGenericPassword(None,len(self.service),self.service,len(account),account,len(raw),raw,None)
        finally:
            if item: self.cf.CFRelease(item)
        if status: raise ValueError(f"Keychain storage failed ({status}); credential was not saved")
    def delete(self, identifier):
        if not self.lib: return
        _,item=self._find(identifier)
        if item:
            try: status=self.lib.SecKeychainItemDelete(item)
            finally: self.cf.CFRelease(item)
            if status: raise ValueError(f"Keychain removal failed ({status})")

def capabilities(provider, model):
    if provider == "codex" and model in {"gpt-6.1-sol","gpt-6-astra","gpt-6-sol","gpt-6-luna","gpt-5.6-sol","gpt-5.6-terra","gpt-5.6-luna"}:
        return ["low","medium","high","xhigh","max"]
    if provider == "grok" and model in {"grok-4.7","grok-4.6","grok-4.7-fast","grok-4.5"}:
        return ["low","medium","high"] + ([] if model == "grok-4.5" else ["xhigh"])
    if provider == "claude" and re.fullmatch(r"claude-(sonnet|opus|fable|mythos)-(5(-[15])?|4-[678])",model):
        return ["low","medium","high"] + ([] if model.endswith("4-6") else ["xhigh"]) + ["max"]
    if provider == "antigravity" and re.fullmatch(r"gemini-3\.[1678]-(flash|pro)(-preview)?",model):
        return ["low","high"] if "3.1-pro" in model else ["low","medium","high"]
    return []

class ConnectionRegistry:
    def __init__(self, store, native=None, vault=None, http_client=None):
        from .providers import ProviderRegistry
        self.store=store;self.native=native or ProviderRegistry();self.vault=vault or CredentialVault();self.http_client=http_client
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY, config TEXT NOT NULL)")
    def configs(self):
        with self.store.connect() as db:
            return [{"id":r["id"],**json.loads(r["config"])} for r in db.execute("SELECT * FROM connections ORDER BY id")]
    def connection(self, identifier):
        config=next((c for c in self.configs() if c["id"]==identifier),None)
        if config is None: raise ValueError("API connection is not configured: "+identifier)
        return config
    def public(self, config):
        configured=bool(self.vault.get(config["id"],config.get("api_key_env")))
        return {**config,"transport":"api","api_configured":configured,"key_hint":"configured" if configured else None,
            "status":"configured" if configured else "credentials_missing","credential_storage":"environment reference" if config.get("api_key_env") else self.vault.storage}
    async def connections(self):
        native=await self.native.discover()
        return [{"id":p["provider"]+"-cli","provider":p["provider"],"name":p.get("name",p["provider"]),"transport":"cli","status":p.get("status"),"cli_status":p,"api_configured":False} for p in native]+[self.public(c) for c in self.configs()]
    async def put(self, identifier, body:ConnectionInput):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}",identifier) or identifier.endswith("-cli"): raise ValueError("Invalid API connection id")
        previous=next((c for c in self.configs() if c["id"]==identifier),{})
        if previous and previous["provider"] != body.provider:
            raise ValueError("An existing connection cannot change provider; create a new connection")
        default=DEFAULTS.get(body.provider)
        protocol=body.protocol or previous.get("protocol") or (default[0] if default else "openai")
        if protocol not in {"responses","anthropic","openai"}: raise ValueError("Unsupported API protocol")
        endpoint=(body.endpoint or previous.get("endpoint") or (default[1] if default else "")).rstrip("/")
        try: parsed=urlsplit(endpoint);parsed.port
        except ValueError: raise ValueError("Invalid API endpoint")
        if any(ord(c)<=32 or ord(c)==127 for c in endpoint): raise ValueError("Invalid API endpoint")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme!="https" and not (parsed.scheme=="http" and parsed.hostname in {"127.0.0.1","localhost","::1"})):
            raise ValueError("API endpoints require HTTPS, except local loopback servers; credentials cannot be in the URL")
        if body.api_key and body.api_key_env: raise ValueError("Choose an API key or an environment reference")
        models=[m.model_dump() for m in body.models] if body.models is not None else previous.get("models",[])
        selected=body.default_model or previous.get("default_model") or (default[2] if default else None)
        if not models and selected: models=[{"id":selected,"label":selected,"efforts":capabilities(body.provider,selected)}]
        if not models or selected not in {m["id"] for m in models}: raise ValueError("Choose an explicit default model from the connection catalog")
        if len({m["id"] for m in models}) != len(models): raise ValueError("Duplicate model ids")
        config={"id":identifier,"provider":body.provider,"name":body.name or previous.get("name") or ("Gemini API" if body.provider=="antigravity" else body.provider.title()+" API"),"protocol":protocol,"endpoint":endpoint,"models":models,"default_model":selected,
                "source":"user-declared catalog" if body.models is not None else previous.get("source","maintained catalog"),"api_key_env":body.api_key_env or (None if body.api_key else previous.get("api_key_env")),
                "credential_version":str(uuid.uuid4()) if body.api_key is not None or body.api_key_env is not None else previous.get("credential_version",str(uuid.uuid4()))}
        if body.api_key:
            key=body.api_key.get_secret_value().strip()
            if not key or len(key)>16000 or any(ord(c)<32 or ord(c)==127 for c in key): raise ValueError("Invalid API key")
            self.vault.set(identifier,key)
        if body.api_key_env: self.vault.delete(identifier)
        with self.store.connect() as db:
            db.execute("INSERT INTO connections VALUES(?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config",(identifier,json.dumps({k:v for k,v in config.items() if k!="id"})))
        return self.public(config)
    def delete(self, identifier):
        self.vault.delete(identifier)
        with self.store.connect() as db: db.execute("DELETE FROM connections WHERE id=?",(identifier,))
        return {"ok":True}
    async def test(self, identifier):
        import httpx
        from .api_agent import ApiFailure, _bounded_json
        config=self.connection(identifier)
        key=self.vault.get(identifier,config.get("api_key_env"))
        if not key: raise ValueError("API credentials are missing")
        headers={"x-api-key":key,"anthropic-version":"2023-06-01"} if config["protocol"]=="anthropic" else {"Authorization":"Bearer "+key}
        owned=self.http_client is None
        client=self.http_client or httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False)
        try:
            status,data=await _bounded_json(client,"GET",config["endpoint"]+"/models",headers=headers,limit=2_000_000,timeout=20)
            if status>=300: return {"ok":False,"status":"authentication_failed" if status in {401,403} else "discovery_failed","message":f"Model discovery returned HTTP {status}; saved settings were preserved"}
            if not isinstance(data,dict): raise ValueError("Endpoint returned an invalid model catalog")
            entries=data.get("data",data.get("models",[]))
            if not isinstance(entries,list): raise ValueError("Endpoint returned an invalid model catalog")
            models=[];seen=set();prior={m["id"]:m for m in config["models"]}
            for entry in entries:
                if not isinstance(entry,dict): continue
                model=entry.get("id",entry.get("name"))
                if not isinstance(model,str) or not 1<=len(model)<=200 or any(ord(c)<32 for c in model): continue
                if config["provider"]=="antigravity": model=model.removeprefix("models/")
                if model in seen: continue
                seen.add(model)
                label=entry.get("display_name",entry.get("displayName",model))
                models.append({"id":model,"label":label[:200] if isinstance(label,str) else model,"efforts":prior.get(model,{}).get("efforts",capabilities(config["provider"],model))})
                if len(models)>=5000: break
            if not models: raise ValueError("Endpoint returned no usable model ids")
            config["models"]=models;config["source"]="account discovery; effort capabilities from maintained or user-declared catalog"
            with self.store.connect() as db: db.execute("UPDATE connections SET config=? WHERE id=?",(json.dumps({k:v for k,v in config.items() if k!="id"}),identifier))
            return {"ok":True,"connection":self.public(config),"default_model_available":config["default_model"] in {m["id"] for m in models}}
        except (httpx.HTTPError,ValueError,ApiFailure): return {"ok":False,"status":"discovery_failed","message":"Cannot discover models from this endpoint; configured settings were preserved"}
        finally:
            if owned: await client.aclose()
    async def discover(self, *, refresh=False):
        return await self.native.discover(refresh=True) if refresh else await self.native.discover()
    async def catalog(self, provider, *, transport="cli", connection_id=None, refresh=False):
        if transport == "cli":
            return await self.native.catalog(provider,refresh=True) if refresh else await self.native.catalog(provider)
        config=self.connection(connection_id or provider+"-api")
        if config["provider"]!=provider: raise ValueError("Connection provider does not match")
        return {"provider":provider,"models":config["models"],"default_model":config["default_model"],"source":config["source"],"transport":"api","connection_id":config["id"]}
    def validate(self, participant:Participant):
        if participant.transport=="cli":
            if participant.provider not in NATIVE: raise ValueError("Custom models require an API connection")
            if participant.connection_id not in {None,participant.provider+"-cli"}: raise ValueError("CLI connection id does not match provider")
            return self.native.validate(participant)
        config=self.connection(participant.connection_id or participant.provider+"-api")
        if config["provider"]!=participant.provider: raise ValueError("API connection belongs to a different provider")
        if not self.vault.get(config["id"],config.get("api_key_env")): raise ValueError("API credentials missing for "+config["id"])
        model=participant.model or config["default_model"]
        entry=next((m for m in config["models"] if m["id"]==model),None)
        if not entry: raise ValueError("Requested model is absent from the connection catalog: "+model)
        if participant.effort and participant.effort not in entry["efforts"]: raise ValueError("Requested effort is unsupported or unverified for "+model)
        return {"provider":participant.provider,"transport":"api","connection_id":config["id"],"model":model,"effort":participant.effort,"endpoint":config["endpoint"],"protocol":config["protocol"],"catalog_source":config["source"],"credential_version":config.get("credential_version")}
    async def run(self, provider, *, transport="cli", connection_id=None, **kwargs):
        if transport=="cli": return await self.native.run(provider,**kwargs)
        from .api_agent import ApiAgent
        p=Participant(provider=provider,transport="api",connection_id=connection_id,model=kwargs.get("model"),effort=kwargs.get("effort"))
        effective=self.validate(p);config=self.connection(effective["connection_id"])
        return await ApiAgent(self.store.home,self.http_client).run(config,key=self.vault.get(config["id"],config.get("api_key_env")),effective=effective,**kwargs)
