"""Persistence logic tests with a fake cipher; DPAPI itself needs Windows."""
import json,tempfile,socket
from pathlib import Path
import unittest
from myrecorder.pairing_store import PairingStore,PairingError,validate
from myrecorder.browser_bridge import Bridge

class Cipher:
    def protect(self,value):return b'fake-encrypted:'+bytes(v^0x5a for v in value)
    def unprotect(self,value):
        if not value.startswith(b'fake-encrypted:'):raise ValueError('bad ciphertext')
        return bytes(v^0x5a for v in value[len(b'fake-encrypted:'):])

class PairingTests(unittest.TestCase):
    def test_store_reloads_credentials_without_plaintext(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'credentials.dpapi';store=PairingStore(path,Cipher())
            self.assertIsNone(store.load())
            pairing={'port':43210,'token':'a'*64};store.save('b'*32,pairing)
            self.assertNotIn(pairing['token'].encode(),path.read_bytes())
            data=PairingStore(path,Cipher()).load()
            self.assertEqual(data['token'],pairing['token']);self.assertEqual(data['extension_id'],'b'*32)
            store.reset();self.assertIsNone(store.load())
    def test_corrupt_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'credentials.dpapi';path.write_bytes(b'broken')
            with self.assertRaises(PairingError):PairingStore(path,Cipher()).load()
            self.assertEqual(path.read_bytes(),b'broken')
    def test_encrypt_failure_never_saves_plaintext(self):
        class Broken(Cipher):
            def protect(self,value):raise OSError('synthetic failure')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'credentials.dpapi'
            with self.assertRaises(PairingError):PairingStore(path,Broken()).save('a'*32,{'port':12345,'token':'b'*64})
            self.assertFalse(path.exists());self.assertFalse(list(Path(d).glob('.pairing-*')))
    def test_invalid_values_rejected(self):
        for field,value in [('port',0),('port',True),('token','bad'),('extension_id','bad')]:
            data={'version':1,'port':12345,'token':'a'*64,'extension_id':'b'*32};data[field]=value
            with self.assertRaises(PairingError):validate(data)
    def test_restart_same_port_token_stays_disarmed(self):
        first=Bridge('a'*32);first.start();port=first.pairing['port'];token=first.token
        first.configure('old-tab',True,'old session');first.close()
        second=Bridge('a'*32,token=token,port=port)
        try:
            second.start();self.assertEqual(second.pairing['port'],port);self.assertEqual(second.token,token)
            self.assertFalse(second.armed);self.assertIsNone(second.selected);self.assertEqual(second.drain(),[])
        finally:second.close()
    def test_port_collision_does_not_choose_another_port(self):
        first=Bridge('a'*32);first.start();self.addCleanup(first.close)
        second=Bridge('a'*32,port=first.pairing['port'])
        with self.assertRaises(OSError):second.start()
    def test_rotation_rejects_old_token(self):
        first=Bridge('a'*32);second=Bridge('a'*32)
        self.assertNotEqual(first.token,second.token)

class SignedTransportTests(unittest.TestCase):
    def setUp(self):
        self.bridge=Bridge('a'*32,signed_only=True);self.bridge.start();self.addCleanup(self.bridge.close)
    def signed(self,token=None):
        import time,hmac,hashlib,secrets
        body=json.dumps({'kind':'snapshot','seq':1,'event_wall_ms':1,'source':{'key':'test','title':'Example',
            'state':'paused','supported':True,'origin':'https://example.invalid','video_label':'video','gate':'play-promise'}}).encode()
        nonce=secrets.token_hex(32);stamp=str(int(time.time()*1000))
        digest=hmac.new((token or self.bridge.token).encode(),f'POST\n/v1/events\n{stamp}\n{nonce}\n'.encode()+body,hashlib.sha256).hexdigest()
        headers={'Authorization':'MyRecorder-HMAC '+digest,'X-MyRecorder-Nonce':nonce,'X-MyRecorder-Time':stamp,
            'X-MyRecorder-Extension':'a'*32,'Content-Type':'application/json','Origin':'chrome-extension://'+'a'*32}
        return body,headers
    def post(self,body,headers):
        import http.client
        connection=http.client.HTTPConnection('127.0.0.1',self.bridge.pairing['port'],timeout=3)
        try:
            connection.request('POST','/v1/events',body,headers)
            response=connection.getresponse();return response.status,response.read(),response.getheader('X-MyRecorder-Proof')
        finally:connection.close()
    def test_signed_request_response_and_replay(self):
        import hashlib,hmac
        body,headers=self.signed();status,result,proof=self.post(body,headers)
        self.assertEqual(status,200)
        expected=hmac.new(self.bridge.token.encode(),f"response\n{headers['X-MyRecorder-Nonce']}\n".encode()+result,hashlib.sha256).hexdigest()
        self.assertEqual(proof,expected);self.assertNotIn(self.bridge.token,headers['Authorization'])
        self.assertEqual(self.post(body,headers)[0],403)
    def test_modified_body_and_old_credentials_rejected(self):
        body,headers=self.signed();self.assertEqual(self.post(body+b' ',headers)[0],403)
        body,headers=self.signed(token='b'*64);self.assertEqual(self.post(body,headers)[0],403)
    def test_persistent_transport_rejects_bearer(self):
        body,headers=self.signed();headers['Authorization']='Bearer '+self.bridge.token
        self.assertEqual(self.post(body,headers)[0],403)

if __name__=='__main__':unittest.main()
