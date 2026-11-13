"""Policy and real loopback HTTP tests; devices are not involved."""
import http.client
import json
import time
import unittest
from myrecorder.browser_bridge import Bridge
from myrecorder.auto_link import AutoLink

ID='a'*32
class AutoTests(unittest.TestCase):
    def setUp(self):
        self.now=10.;self.bridge=Bridge(ID,clock=lambda:self.now);self.seq=0;self.events=[]
        self.source={'key':'browser:1:document:video','title':'Example Lecture','origin':'https://example.invalid',
                     'video_label':'video 1','state':'paused','supported':True,'gate':'play-promise'}
        self.send('snapshot');self.auto=AutoLink(self.bridge,lambda e,**k:self.events.append((e,k)),clock=lambda:self.now)
        self.auto.arm(self.source['key'],'lecture')
    def send(self,kind,key=None,request=None):
        self.seq+=1;source={**self.source,'key':key or self.source['key']}
        return self.bridge.ingest({'kind':kind,'source':source,'seq':self.seq,'event_wall_ms':time.time()*1000,'request_id':request})
    def tick(self,state,busy=False):return self.auto.tick(state,busy,'lecture')
    def test_warmup_then_five_pause_resume_ready_cycles(self):
        self.assertEqual(self.tick('idle'),'start')
        self.assertIsNone(self.tick('recording'));self.now+=1
        self.assertEqual(self.tick('recording'),'pause');self.tick('paused')
        for i in range(5):
            request=f'request-{i}';self.send('prepare',request=request)
            self.assertEqual(self.tick('paused'),'resume')
            self.assertIsNone(self.tick('recording'));self.now+=1
            self.tick('recording');self.assertEqual(self.bridge.replies[request]['status'],'ready')
            self.send('pause');self.assertIsNone(self.tick('recording'))
            self.now+=1.1;self.assertEqual(self.tick('recording'),'pause');self.tick('paused')
        self.assertEqual(sum(e=='ready_ack' for e,k in self.events),5)
    def test_manual_pause_never_resumes_from_browser(self):
        self.tick('recording');self.auto.manual('pause');self.tick('paused')
        self.send('prepare',request='blocked');self.assertIsNone(self.tick('paused'))
        self.assertEqual(self.bridge.replies['blocked']['status'],'blocked')
        self.send('playing');self.assertIsNone(self.tick('paused'))
        self.auto.manual('resume');self.assertFalse(self.auto.manual_hold)
    def test_buffering_and_other_tab_do_not_pause(self):
        self.send('prepare',request='first');self.tick('recording');self.now+=1;self.tick('recording')
        self.send('buffering');self.assertIsNone(self.tick('recording'))
        self.send('pause',key='other:tab');self.assertIsNone(self.tick('recording'))
    def test_fast_resume_cancels_tail_pause(self):
        self.send('playing');self.tick('recording');self.now+=1
        self.send('pause');self.tick('recording');self.now+=.2
        self.send('prepare',request='fast');self.assertIsNone(self.tick('recording'))
        self.now+=1;self.assertIsNone(self.tick('recording'))
        self.assertEqual(self.bridge.replies['fast']['status'],'ready')
    def test_disconnect_disables_but_does_not_stop_capture(self):
        self.tick('recording');self.now+=9
        self.assertIsNone(self.tick('recording'));self.assertFalse(self.auto.enabled)
    def test_general_mode_never_dispatches(self):
        self.assertIsNone(self.auto.tick('idle',False,'general'));self.assertFalse(self.auto.enabled)
    def test_ended_stop_is_explicit_option(self):
        self.send('ended');self.tick('recording');self.now+=2
        self.assertEqual(self.tick('recording'),'pause')
        self.auto.end_stops=True;self.send('ended');self.tick('paused');self.now+=2
        self.assertEqual(self.tick('paused'),'stop')
    def test_unsupported_and_old_sources_cannot_arm(self):
        self.now+=5
        with self.assertRaises(ValueError):self.auto.arm(self.source['key'],'lecture')
    def test_replay_rejected_and_old_ack_revoked_on_disable(self):
        self.send('prepare',request='old');self.bridge.resolve('old','ready')
        self.auto.disable()
        result=self.send('poll',request='old');self.assertEqual(result['reply']['status'],'blocked')
        with self.assertRaises(ValueError):self.bridge.ingest({'kind':'snapshot','source':self.source,'seq':self.seq,'event_wall_ms':1})
    def test_unsupported_event_disables_without_stopping(self):
        self.tick('recording');self.source['supported']=False
        self.send('unsupported')
        self.assertIsNone(self.tick('recording'));self.assertFalse(self.auto.enabled)

    def test_browser_play_failure_retains_manual_control(self):
        self.tick('recording');self.send('play_failed')
        self.assertIsNone(self.tick('recording'));self.assertFalse(self.auto.enabled)

    def test_saving_completion_does_not_start_new_session(self):
        self.tick('recording');self.tick('saving',True)
        self.assertIsNone(self.tick('idle'));self.assertFalse(self.auto.enabled)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.bridge=Bridge(ID);self.bridge.start();self.addCleanup(self.bridge.close)
        self.port=self.bridge.pairing['port']
        self.source={'key':'example','title':'Example','origin':'https://example.invalid','video_label':'video 1','state':'paused','supported':True,'gate':'play-promise'}
    def request(self,headers=None,body=None,path='/v1/events'):
        base={'Content-Type':'application/json','Origin':'chrome-extension://'+ID,
              'X-MyRecorder-Extension':ID,'Authorization':'Bearer '+self.bridge.token}
        base.update(headers or {})
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        try:
            connection.request('POST',path,body=body or json.dumps({'kind':'snapshot','source':self.source,'seq':1,'event_wall_ms':1}),headers=base)
            response=connection.getresponse();data=response.read();return response.status,data
        finally:connection.close()
    def test_valid_request(self):self.assertEqual(self.request()[0],200)
    def test_wrong_origin_token_extension_host_and_path_rejected(self):
        for headers in [{'Origin':'https://evil.invalid'},{'Authorization':'Bearer wrong'},
                        {'X-MyRecorder-Extension':'b'*32},{'Host':'evil.invalid'}]:
            self.assertEqual(self.request(headers)[0],403)
        self.assertEqual(self.request(path='/wrong')[0],403)
    def test_oversize_and_non_json_rejected(self):
        self.assertEqual(self.request(body='x'*17000)[0],413)
        self.assertEqual(self.request({'Content-Type':'text/plain'})[0],415)
    def test_unauthenticated_request_does_not_reach_policy(self):
        self.request({'Authorization':'Bearer wrong'})
        self.assertEqual(self.bridge.snapshot(),[])

if __name__=='__main__':unittest.main()
