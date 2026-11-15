"""Run the shared URL validator with Node; optional Node needed for these dev tests."""
from pathlib import Path
import shutil,subprocess,unittest

@unittest.skipUnless(shutil.which('node'),'Node unavailable for extension validator tests')
class PopupTargetTests(unittest.TestCase):
    def run_js(self,body):
        helper=Path(__file__).resolve().parents[1]/'browser_extension'/'popup_tabs.js'
        code="const assert=require('node:assert/strict');require(process.argv[1]);"+body
        subprocess.run(['node','-e',code,str(helper)],check=True,capture_output=True,text=True)
    def test_missing_metadata_has_actionable_error(self):
        self.run_js("for(const url of [undefined,null,'']) assert.throws(()=>PopupTabs.target({id:1,url}),e=>e.code==='MISSING_URL' && !e.message.includes('Invalid URL'));")
    def test_missing_tab_and_invalid_id_rejected(self):
        self.run_js("for(const tab of [null,{}, {id:-1,url:'https://example.invalid'}]) assert.throws(()=>PopupTabs.target(tab),e=>e.code==='NO_TAB');")
    def test_internal_file_and_extension_pages_rejected(self):
        self.run_js("for(const url of ['chrome://extensions','edge://settings','about:blank','file:///example.html','chrome-extension://example/popup.html']) assert.throws(()=>PopupTabs.target({id:1,url}),e=>e.code==='UNSUPPORTED_URL');")
    def test_malformed_url_does_not_echo_private_text(self):
        self.run_js("assert.throws(()=>PopupTabs.target({id:1,url:'invalid secret-string'}),e=>e.code==='INVALID_URL' && !e.message.includes('secret-string'));")
    def test_http_port_and_hash_are_handled(self):
        self.run_js("const t=PopupTabs.target({id:7,url:'http://127.0.0.1:12345/index.html#x'});assert.equal(t.pattern,'http://127.0.0.1/*');assert.equal(t.documentUrl,'http://127.0.0.1:12345/index.html');assert.equal(t.id,7);")
    def test_credentials_in_url_not_registered(self):
        self.run_js("assert.throws(()=>PopupTabs.target({id:1,url:'https://user:password@example.invalid/'}),e=>e.code==='URL_CREDENTIALS');")

if __name__=='__main__':unittest.main()
