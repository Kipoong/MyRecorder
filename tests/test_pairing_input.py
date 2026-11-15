from pathlib import Path
import shutil,subprocess,unittest
from myrecorder.browser_bridge import Bridge

@unittest.skipUnless(shutil.which('node'),'Node unavailable for extension parser tests')
class PairingInputTests(unittest.TestCase):
    def run_js(self,code):
        helper=Path(__file__).resolve().parents[1]/'browser_extension/pairing_input.js'
        subprocess.run(['node','-e',"const assert=require('node:assert/strict');require(process.argv[1]);"+code,str(helper)],check=True,capture_output=True,text=True)
    def test_empty_input_has_specific_code(self):
        self.run_js("assert.throws(()=>PairingInput.parse('  '),e=>e.code==='INPUT_EMPTY');")
    def test_filename_is_not_json_body(self):
        self.run_js("assert.throws(()=>PairingInput.parse('connection.json'),e=>e.code==='INPUT_JSON' && !e.message.includes('connection.json'));")
    def test_bom_and_whitespace_accepted(self):
        self.run_js("const p=PairingInput.parse('\\ufeff '+JSON.stringify({port:12345,token:'a'.repeat(64)})+' ');assert.equal(p.port,12345);assert.equal(p.token.length,64);")
    def test_schema_and_size_rejected_without_echoing_secret(self):
        self.run_js("assert.throws(()=>PairingInput.parse(JSON.stringify({port:'12345',token:'secret'})),e=>e.code==='INPUT_SCHEMA' && !e.message.includes('secret'));assert.throws(()=>PairingInput.parse('x'.repeat(9000)),e=>e.code==='INPUT_TOO_LARGE');")
    def test_unrelated_fields_are_not_saved(self):
        self.run_js("const p=PairingInput.parse(JSON.stringify({port:12345,token:'a'.repeat(64),extra:'private'}));assert.deepEqual(Object.keys(p),['port','token']);")

class ProbeTests(unittest.TestCase):
    def test_ping_does_not_create_source_event_or_arm_capture(self):
        bridge=Bridge('a'*32)
        self.assertEqual(bridge.ingest({'kind':'ping'}),{'connection':'ready','protocol':1})
        self.assertFalse(bridge.armed);self.assertIsNone(bridge.selected)
        self.assertEqual(bridge.snapshot(),[]);self.assertEqual(bridge.drain(),[])

if __name__=='__main__':unittest.main()
