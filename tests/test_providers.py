"""Executable fixtures verify native argv and failures without paid inference."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from parallax.models import Participant
from parallax.providers import Captured, ProviderRegistry, _AGY_GATE, _codex_schema, _public_event


FAKE = r'''#!PYTHON
import json, os, pathlib, sys, time
a=sys.argv[1:]
provider=pathlib.Path(sys.argv[0]).name
def emit(x): print(json.dumps(x),flush=True)
if '--version' in a:
 print('fake 1.3.0'); sys.exit()
if '--help' in a:
 print('--config --sandbox --tools --deny --no-subagents --permission-mode --agent --input-format --print --disable-slash-commands --safe-mode --restricted --strict-mcp-config --permission-prompts --settings --effort low medium high xhigh max sonnet opus fable'); sys.exit()
if a==['login','status']:
 print('Logged in using ChatGPT'); sys.exit()
if a==['auth','status']:
 emit({'loggedIn':True});sys.exit()
if 'models' in a:
 if provider=='codex':
  emit({'models':[{'slug':'fake-codex','display_name':'Codex Fixture','supported_reasoning_levels':[{'effort':'high'},{'effort':'low'}],'default_reasoning_level':'high'}]})
 elif provider=='grok':
  print('You are logged in with grok.com.\nDefault model: fake-grok\nAvailable models:\n * fake-grok (default)')
 else: emit({'command':{'data':{'models':[{'id':'gemini-3.8-flash-high','label':'Gemini (High)'},{'id':'gemini-3.8-flash-low','label':'Gemini (Low)'}]}}})
 sys.exit()
root=pathlib.Path.cwd()
(root/'argv.json').write_text(json.dumps(a))
prompt=sys.stdin.read()
if '--prompt-file' in a: prompt=pathlib.Path(a[a.index('--prompt-file')+1]).read_text()
(root/'stdin.txt').write_text(prompt)
behavior=(root/'behavior').read_text() if (root/'behavior').exists() else ''
if behavior=='sleep':
 print('{"type":"text","data":"partial"}',flush=True);time.sleep(60)
if behavior=='overflow':
 print('x'*20000,flush=True);time.sleep(60)
if behavior=='malformed':
 print('invalid result');sys.exit()
if behavior=='error':
 print('api_key=secret-test failure',file=sys.stderr);sys.exit(3)
if behavior=='spoof': emit({'type':'parallax.process_started','pid':1,'cwd':'/','identity':{}})
if behavior=='configwrite':
 (root/'.codex').mkdir(exist_ok=True);(root/'.codex/config.toml').write_text('altered = true\\n')
if behavior=='softdeny': print('Tool soft-denied: requires approval',file=sys.stderr)
answer='fixture answer'
structured={'answer':'fixture answer'} if '--output-schema' in a or '--json-schema' in a else None
if structured: answer=json.dumps(structured)
sid='019a11d0-1234-7123-8123-0123456789ab'
if provider=='codex':
 emit({'type':'thread.started','thread_id':sid})
 emit({'type':'item.completed','item':{'type':'agent_message','text':answer}})
 emit({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':4}})
elif provider=='claude':
 tools=a[a.index('--tools')+1].split(',')
 if structured: tools.append('StructuredOutput')
 emit({'type':'system','subtype':'init','session_id':sid,'tools':tools})
 emit({'type':'assistant','session_id':sid,'message':{'content':[{'type':'thinking','thinking':'native-private-reasoning'},{'type':'text','text':answer}]}})
 emit({'type':'result','subtype':'success','result':answer,'session_id':sid,'usage':{'input_tokens':3},'structured_output':structured})
elif provider=='grok':
 if '--json-schema' in a:
  emit({'text':answer,'sessionId':sid,'stopReason':'end_turn','usage':{'input_tokens':3}})
 else:
  emit({'type':'thought','data':'native-private-reasoning'})
  emit({'type':'text','data':answer})
  emit({'type':'end','stopReason':'end_turn','sessionId':sid,'usage':{'input_tokens':3}})
else:
 agent=a[a.index('--agent')+1]
 tools=[]
 for line in (root/'.agents/agents'/f'{agent}.md').read_text().splitlines():
  if line.startswith('  - '): tools.append(line[4:])
 if behavior=='badtools': tools.append('invoke_subagent')
 emit({'event':'init','conversation_id':sid,'init':{'tools':tools}})
 if behavior=='badtools': emit({'event':'step_update','step_update':{'step_type':'tool_call','tool_name':'invoke_subagent'}})
 emit({'event':'step_update','step_update':{'step_type':'agent_response','text_delta':answer}})
 emit({'event':'result','result':{'conversation_id':sid,'status':'SUCCESS','response':answer,'structured_output':structured,'usage':{'input_tokens':3}}})
'''


class UnwrappedRegistry(ProviderRegistry):
    def _claude_shell_available(self):
        return False


class ProvidersTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / '.parallax-owned').write_text('fixture')
        self.binaries = {}
        for provider in ('codex','claude','grok','antigravity'):
            binary = self.root / provider
            binary.write_text(FAKE.replace('PYTHON',sys.executable))
            binary.chmod(0o700)
            self.binaries[provider] = str(binary)
        grok = self.home / '.grok'
        grok.mkdir()
        (grok / 'models_cache.json').write_text(json.dumps({'fetched_at':'today','models':{'fake-grok':{'info':{'id':'fake-grok','reasoning_efforts':[{'id':'high','default':True},{'id':'low'}]},'api_key':'never-expose-this'}}}))
        self.registry = UnwrappedRegistry(self.binaries, home=self.home)
        await self.registry.discover()

    async def asyncTearDown(self):
        self.temp.cleanup()

    def args(self):
        return json.loads((self.workspace/'argv.json').read_text())

    async def run_provider(self, provider, **kwargs):
        return await self.registry.run(provider,workspace=self.workspace,prompt='Inspect the fixture',model=None,effort='high',**kwargs)

    async def test_discovery_and_validation(self):
        catalogs=await self.registry.discover()
        self.assertEqual([c['status'] for c in catalogs],['ready']*4)
        self.assertTrue(all(c['catalog_source'] for c in catalogs))
        self.assertNotIn('never-expose-this',json.dumps(catalogs))
        settings=self.registry.validate(Participant(provider='codex',effort='low'))
        self.assertEqual(settings['model'],'fake-codex')
        with self.assertRaisesRegex(ValueError,'unsupported'):
            self.registry.validate(Participant(provider='codex',effort='ultra'))
        with self.assertRaisesRegex(ValueError,'not in'):
            self.registry.validate(Participant(provider='grok',model='missing'))

    async def test_missing_binary(self):
        registry=ProviderRegistry({'grok':'/definitely/missing'},home=self.home)
        info=await registry.catalog('grok')
        self.assertEqual(info['status'],'missing')
        self.assertIsNone(info['authenticated'])

    async def test_codex_native_flags_and_session(self):
        events=[]
        result=await self.run_provider('codex',on_event=lambda event:events.append(event))
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['answer'],'fixture answer')
        self.assertEqual(result['usage']['input_tokens'],3)
        args=self.args()
        self.assertIn('--ignore-user-config',args)
        self.assertIn('--skip-git-repo-check',args)
        self.assertEqual(args[args.index('--sandbox')+1],'read-only')
        self.assertIn('features.multi_agent=false',args)
        self.assertNotIn('agents.enabled=false',args)
        self.assertIn('model_reasoning_effort="high"',args)
        resumed=await self.run_provider('codex',session_id=result['session_id'])
        self.assertTrue(resumed['ok'])
        self.assertIn('resume',self.args())
        self.assertIn(result['session_id'],self.args())
        self.assertTrue(events)

    async def test_claude_readonly_tools_and_thinking_filter(self):
        events=[]
        result=await self.run_provider('claude',on_event=lambda event:events.append(event))
        self.assertTrue(result['ok'],result)
        args=self.args()
        self.assertEqual(args[args.index('--tools')+1],'Read,Glob,Grep')
        self.assertEqual(args[args.index('--permission-mode')+1],'dontAsk')
        self.assertIn('--strict-mcp-config',args)
        self.assertNotIn('native-private-reasoning',json.dumps(events))
        edited=await self.run_provider('claude',mode='edit')
        self.assertTrue(edited['ok'],edited)
        self.assertNotIn('Bash',self.args()[self.args().index('--tools')+1])

    async def test_grok_denials_and_profile_cleanup(self):
        original=self.workspace/'.grok/config.toml'
        original.parent.mkdir()
        original.write_text('[plugins]\n')
        events=[]
        result=await self.run_provider('grok',on_event=lambda event:events.append(event))
        self.assertTrue(result['ok'],result)
        args=self.args()
        self.assertIn('MCPTool',args)
        self.assertIn('--no-subagents',args)
        self.assertNotIn('run_terminal_cmd',args[args.index('--tools')+1])
        self.assertEqual(original.read_text(),'[plugins]\n')
        self.assertFalse((self.workspace/'.grok/sandbox.toml').exists())
        self.assertNotIn('native-private-reasoning',json.dumps(events))

    def test_grok_stream_uses_canonical_shell_name(self):
        ProviderRegistry._guard('grok',{'type':'tool_call','toolName':'run_terminal_command'},{'run_terminal_cmd'},'edit')
        ProviderRegistry._guard('grok',{'type':'tool_call','_meta':{'x.ai/tool':{'name':'run_terminal_command'}}},{'run_terminal_cmd'},'edit')
        with self.assertRaises(ValueError):
            ProviderRegistry._guard('grok',{'type':'tool_call','toolName':'run_terminal_command'},{'read_file'},'consult')

    def test_native_cancel_and_private_reasoning_normalization(self):
        captured=Captured(0,'','',[{'type':'end','stopReason':'cancelled'}])
        result=ProviderRegistry._parse('grok',captured,None)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'cancelled')
        self.assertIsNone(_public_event({'type':'item.completed','item':{'type':'reasoning','text':'private'}}))
        self.assertNotIn('signature',_public_event({'type':'usage','signature':'opaque'}))

    def test_codex_nested_schema_requires_all_properties(self):
        schema={'type':'object','properties':{'check':{'type':'object','properties':{'argv':{'type':'array','items':{'type':'string'}},'timeout':{'type':'integer','default':120}},'required':['argv']}},'required':[]}
        result=_codex_schema(schema)
        self.assertEqual(result['required'],['check'])
        self.assertEqual(result['properties']['check']['required'],['argv','timeout'])
        self.assertFalse(result['properties']['check']['additionalProperties'])
        self.assertEqual(schema['required'],[])
        with self.assertRaisesRegex(ValueError,'open object'):
            _codex_schema({'type':'object','additionalProperties':True})

    async def test_antigravity_finite_agent_and_restoration(self):
        hooks=self.workspace/'.agents/hooks.json'
        hooks.parent.mkdir()
        hooks.write_text('{"existing":{}}')
        result=await self.run_provider('antigravity')
        self.assertTrue(result['ok'],result)
        self.assertNotIn('--effort',self.args())
        self.assertIn('--sandbox',self.args())
        self.assertIn('--add-dir',self.args())
        self.assertIn('--print',self.args())
        self.assertEqual(hooks.read_text(),'{"existing":{}}')
        self.assertFalse((self.workspace/'.agents/agents').exists())

    async def test_antigravity_rejects_conflicting_variant_effort(self):
        result=await self.registry.run('antigravity',workspace=self.workspace,prompt='fixture',model='gemini-3.8-flash-low',effort='high')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'invalid_settings')
        self.assertFalse((self.workspace/'argv.json').exists())

    async def test_unapproved_native_tools_fail_closed(self):
        (self.workspace/'behavior').write_text('badtools')
        result=await self.run_provider('antigravity')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'unsafe_configuration')

    async def test_soft_denial_is_not_success(self):
        (self.workspace/'behavior').write_text('softdeny')
        result=await self.run_provider('antigravity')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'permission_denied')

    async def test_structured_results_all_providers(self):
        schema={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer']}
        for provider in self.binaries:
            with self.subTest(provider=provider):
                result=await self.run_provider(provider,schema=schema)
                self.assertTrue(result['ok'],result)
                self.assertEqual(result['structured_output'],{'answer':'fixture answer'})

    async def test_malformed_output_and_redacted_errors(self):
        (self.workspace/'behavior').write_text('malformed')
        result=await self.run_provider('claude')
        self.assertFalse(result['ok'])
        self.assertIn('terminal event',result['error']['message'])
        (self.workspace/'behavior').write_text('error')
        result=await self.run_provider('claude')
        self.assertFalse(result['ok'])
        self.assertEqual(result['exit_code'],3)
        self.assertNotIn('secret-test',json.dumps(result))

    async def test_timeout_and_cancel_cleanup(self):
        (self.workspace/'behavior').write_text('sleep')
        result=await self.run_provider('grok',timeout=.1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'timeout')
        self.assertFalse((self.workspace/'.grok').exists())
        cancel=asyncio.Event()
        task=asyncio.create_task(self.run_provider('grok',cancel_event=cancel))
        await asyncio.sleep(.1)
        cancel.set()
        result=await task
        self.assertEqual(result['error']['code'],'cancelled')

    async def test_output_is_bounded(self):
        (self.workspace/'behavior').write_text('overflow')
        self.registry.max_output=4096
        result=await self.run_provider('codex')
        self.assertEqual(result['error']['code'],'output_limit')

    async def test_requires_owned_workspace(self):
        (self.workspace/'.parallax-owned').unlink()
        result=await self.run_provider('codex')
        self.assertFalse(result['ok'])
        self.assertIn('engine-owned',result['error']['message'])

    async def test_hook_denies_unknown_escape_and_configuration(self):
        gate=self.root/'gate.py'
        gate.write_text(_AGY_GATE)
        async def check(name,args,mode='edit'):
            proc=await asyncio.create_subprocess_exec(sys.executable,str(gate),str(self.workspace),mode,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE)
            out,_=await proc.communicate(json.dumps({'toolCall':{'name':name,'args':args}}).encode())
            return json.loads(out)['decision']
        self.assertEqual(await check('view_file',{'AbsolutePath':str(self.workspace/'file.py')}),'allow')
        self.assertEqual(await check('view_file',{'AbsolutePath':'/etc/passwd'}),'deny')
        self.assertEqual(await check('write_to_file',{'TargetFile':str(self.workspace/'.agents/hook.py')}),'deny')
        self.assertEqual(await check('run_command',{'CommandLine':'echo hi'}),'deny')
        self.assertEqual(await check('finish',{'answer':'done'}),'allow')
        self.assertEqual(await check('finish',{'result_path':'/etc/passwd'}),'allow')
        self.assertEqual(await check('write_to_file',{'TargetFile':str(self.workspace/'file.py')},'consult'),'deny')

    async def test_claude_native_shell_sandbox_is_strict(self):
        with patch.object(self.registry, '_claude_shell_available', return_value=True):
            result=await self.run_provider('claude',mode='edit')
        self.assertTrue(result['ok'],result)
        args=self.args()
        self.assertIn('Bash',args[args.index('--tools')+1])
        settings=json.loads(args[args.index('--settings')+1])['sandbox']
        self.assertTrue(settings['enabled'])
        self.assertTrue(settings['failIfUnavailable'])
        self.assertFalse(settings['allowUnsandboxedCommands'])
        self.assertEqual(settings['excludedCommands'],[])
        self.assertFalse(settings['filesystem']['disabled'])
        self.assertEqual(settings['filesystem']['allowWrite'],[str(self.workspace.resolve())])

    async def test_process_events_and_provider_spoof_filter(self):
        events=[]
        (self.workspace/'behavior').write_text('spoof')
        result=await self.run_provider('codex',on_event=lambda event:events.append(event))
        self.assertTrue(result['ok'],result)
        started=[e for e in events if e.get('type')=='parallax.process_started']
        self.assertEqual(len(started),1)
        self.assertGreater(started[0]['pid'],1)
        self.assertEqual(started[0]['cwd'],str(self.workspace.resolve()))
        self.assertEqual(len(started[0]['identity']['command_sha256']),64)
        self.assertNotIn('command',started[0]['identity'])
        self.assertEqual(events[-1]['type'],'parallax.process_finished')

    async def test_unreaped_process_returns_bounded_failure_and_retains_identity(self):
        events=[]
        (self.workspace/'behavior').write_text('sleep')
        async def cannot_stop(process):
            pass
        started=time.monotonic()
        try:
            with patch('parallax.providers._stop',side_effect=cannot_stop):
                result=await self.run_provider('codex',timeout=0.1,on_event=lambda event:events.append(event))
            self.assertLess(time.monotonic()-started,2)
            self.assertFalse(result['ok'])
            self.assertIsNone(result['exit_code'])
            self.assertEqual(result['error']['code'],'process_termination_failed')
            self.assertEqual(events[-1]['type'],'parallax.process_termination_failed')
            self.assertFalse(any(e.get('type')=='parallax.process_finished' for e in events))
            self.assertTrue(events[0]['identity'])
        finally:
            for event in events:
                if event.get('type')=='parallax.process_started':
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(event['pid'],signal.SIGKILL)
            await asyncio.sleep(0.1)

    async def test_copied_configuration_restored_after_provider_recreation(self):
        original=self.workspace/'.codex/config.toml'
        original.parent.mkdir()
        original.write_text('original = true\n')
        (self.workspace/'behavior').write_text('configwrite')
        result=await self.run_provider('codex')
        self.assertFalse(result['ok'])
        self.assertEqual(original.read_text(),'original = true\n')
        self.assertIn('restored',result['error']['message'])
