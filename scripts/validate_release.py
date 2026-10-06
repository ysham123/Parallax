#!/usr/bin/env python3
"""Offline release consistency checks; no provider access or inference."""
from pathlib import Path
import json
import re
import sys
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from release_files import release_files

root=Path(__file__).resolve().parents[1]
errors=[]
def check(condition,message):
    if not condition: errors.append(message)
versions=[]
manifests={}
for name in ("plugin.json",".codex-plugin/plugin.json","studio/package.json"):
    doc=json.loads((root/name).read_text());manifests[name]=doc;versions.append(doc["version"])
    if "plugin" in name: check(doc["name"]=="codex-claude-team",name+" changes the installation ID")
check(len(set(versions))==1 and versions[0]=="1.1.0","Manifest versions differ")
check('version = "1.1.0"' in (root/"pyproject.toml").read_text(),"Python package version differs")
check('__version__ = "1.1.0"' in (root/"src/parallax/__init__.py").read_text(),"Runtime version differs")
portable=manifests["plugin.json"]
compatibility=manifests[".codex-plugin/plugin.json"]
check(portable.get("$schema")=="https://agent-plugins.org/schemas/1.0.0/plugin.schema.json","Portable plugin schema differs")
overlay=portable.get("extensions",{}).get("com.openai",{})
check(overlay.get("interface")==compatibility.get("interface"),"Portable and Codex listing metadata differ")
check(compatibility.get("skills")=="./skills/","Codex skill root differs")
check(overlay.get("mcpServers")==compatibility.get("mcpServers")=="./.mcp.json","Codex MCP component path differs")
for field in ("composerIcon","logo","composerIconDark","logoDark"):
    value=overlay.get("interface",{}).get(field)
    if value:
        check(isinstance(value,str) and value.startswith("./") and ".." not in Path(value).parts and (root/value).is_file(),"Missing or unsafe listing asset: "+field)
        asset=root/value
        if asset.is_file():
            check(asset.stat().st_size<=5*1024*1024,"Listing asset exceeds 5 MiB: "+field)
            check(asset.suffix.lower() in {".svg",".png",".jpg",".jpeg",".webp"},"Unsupported listing asset format: "+field)
            if asset.suffix.lower()==".svg":
                try:
                    element=ET.parse(asset).getroot()
                    box=element.attrib.get("viewBox","").replace(","," ").split()
                    width,height=(map(float,box[2:]) if len(box)==4 else (float(element.attrib.get("width","0")),float(element.attrib.get("height","0"))))
                    check(width==height and width>=48,"SVG listing asset must be square and at least 48 pixels: "+field)
                except (ET.ParseError,ValueError,OSError):
                    check(False,"Invalid SVG listing asset dimensions: "+field)
for value in overlay.get("interface",{}).get("screenshots",[]):
    check(isinstance(value,str) and value.startswith("./") and ".." not in Path(value).parts and (root/value).is_file(),"Missing or unsafe screenshot: "+str(value))
legacy=root/"scripts/claude_bridge.py";check(legacy.exists(),"Legacy bridge missing")
servers={}
for manifest in (".mcp.json","mcp.json"):
    doc=json.loads((root/manifest).read_text());server=doc["mcpServers"]["parallax"]
    servers[manifest]=server
    check(server["command"]=="./scripts/launch.sh" and server["args"]==["mcp"],manifest+" has an inconsistent entry point")
    check(server.get("cwd")==".",manifest+" must resolve its launcher from the plugin root")
    check(not server.get("env"),manifest+" must not embed environment values or credentials")
    if manifest=="mcp.json":
        check(doc.get("$schema")=="https://agent-plugins.org/schemas/1.0.0/mcp.schema.json" and server.get("type")=="stdio","Portable MCP transport schema differs")
check(servers[".mcp.json"].get("env_vars")==servers["mcp.json"].get("env_vars"),"MCP environment allowlists differ")
check({"OPENAI_API_KEY","ANTHROPIC_API_KEY","XAI_API_KEY","GROK_API_KEY","GEMINI_API_KEY","GOOGLE_API_KEY"}.issubset(set(servers[".mcp.json"].get("env_vars",[]))),"MCP environment allowlist omits standard API references")
check((root/"scripts/launch.sh").stat().st_mode&0o111,"MCP launcher is not executable")
lock=root/"requirements.lock"
check(lock.exists(),"Hashed runtime dependency lock missing")
if lock.exists():
    records=re.split(r"\n(?=[a-zA-Z0-9])",lock.read_text())
    for record in records:
        if record.lstrip().startswith("#"): continue
        check(bool(re.match(r"^[a-zA-Z0-9_.-]+==[^\s;\\]+",record)),"Runtime lock contains an unpinned requirement")
        check(bool(re.search(r"--hash=sha256:[a-f0-9]{64}(?:\s|$)",record)),"Runtime lock requirement lacks an artifact hash")
check((root/"studio/package-lock.json").exists(),"Studio dependency lock missing")
check((root/".agents/plugins/marketplace.json").exists(),"Marketplace manifest missing")
marketplace=json.loads((root/".agents/plugins/marketplace.json").read_text())
entries=marketplace.get("plugins",[])
check(marketplace.get("name")=="codex-claude-team","Marketplace identity differs")
check(len(entries)==1 and entries[0].get("name")=="codex-claude-team","Marketplace plugin identity differs")
if len(entries)==1:
    check(entries[0].get("source")=={"source":"url","url":"https://github.com/ysham123/codex-claude-team.git"},"Repository marketplace source differs")
skill=(root/"skills/codex-claude-team/SKILL.md").read_text()
check(skill.startswith("---\nname: codex-claude-team\ndescription:"),"Skill front matter differs from install identity")
check("API" in skill and "Activate when requested" in skill,"Skill boundaries missing")
static=root/"src/parallax/static"
class Assets(HTMLParser):
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        for key in ("src","href"):
            value=attrs.get(key,"")
            if value and not value.startswith(("data:","http:","https:","#")):
                check((static/value.lstrip("./")).is_file(),"Missing packaged asset: "+value)
check((static/"index.html").exists(),"Prebuilt Studio missing")
if (static/"index.html").exists(): Assets().feed((static/"index.html").read_text())
try:
    files=release_files(root)
except (OSError,ValueError) as exc:
    errors.append(str(exc));files=[]
def check_public_identity(value,path):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in {"session_id","sessionId","conversation_id","conversationId"} and item:
                check(isinstance(item,str) and item in {"[redacted]","<private-session>"},"Private native session identity in "+path)
            check_public_identity(item,path)
    elif isinstance(value,list):
        for item in value: check_public_identity(item,path)
for path in files:
    relative=str(path.relative_to(root))
    if relative.startswith("docs/") and path.suffix in {".json",".md",".txt"}:
        content=path.read_text()
        check(not re.search(r"/(?:Users|home)/[^\s\"'<>]+",content),"Private home path in "+relative)
        if path.suffix==".json": check_public_identity(json.loads(content),relative)
if errors:
    print("\n".join(errors),file=sys.stderr);raise SystemExit(1)
print("Release consistency passed: 1.1.0 manifests, marketplace, portable MCP, legacy wrapper, locks, skill, and Studio assets.")
