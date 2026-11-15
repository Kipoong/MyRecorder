from pathlib import Path
import shutil,subprocess,unittest

@unittest.skipUnless(shutil.which('node'),'Node unavailable for extension sender tests')
class UiSenderTests(unittest.TestCase):
    def run_js(self,code):
        helper=Path(__file__).resolve().parents[1]/'browser_extension/ui_sender.js'
        subprocess.run(['node','-e',"const assert=require('node:assert/strict');require(process.argv[1]);const id='a'.repeat(32),url='chrome-extension://'+id+'/popup.html';"+code,str(helper)],check=True,capture_output=True,text=True)
    def test_popup_query_and_fragment_are_same_trusted_document(self):
        self.run_js("for(const suffix of ['', '?context=example','#view','?x=1#y'])assert.equal(UiSender.allowed({id,url:url+suffix},id),true);")
    def test_content_script_is_not_privileged_ui(self):
        self.run_js("assert.equal(UiSender.allowed({id,url:'https://example.invalid/popup.html',origin:'https://example.invalid',tab:{id:1}},id),false);")
    def test_other_extension_documents_rejected(self):
        self.run_js("assert.equal(UiSender.allowed({id,url:url.replace('popup.html','other.html')},id),false);assert.equal(UiSender.allowed({id,url:url.replace(id,'b'.repeat(32))},id),false);")
    def test_origin_fallback_only_for_extension_popup_without_tab(self):
        self.run_js("assert.equal(UiSender.allowed({id,origin:'chrome-extension://'+id},id),true);assert.equal(UiSender.allowed({origin:'chrome-extension://'+id},id),true);assert.equal(UiSender.allowed({id,origin:'chrome-extension://'+id,tab:{id:2}},id),false);")
    def test_conflicting_extension_id_rejected(self):
        self.run_js("assert.equal(UiSender.allowed({id:'b'.repeat(32),url},id),false);")
    def test_unknown_or_malformed_sender_rejected(self):
        self.run_js("for(const sender of [undefined,null,{}, {id}, {id,url:'invalid'}])assert.equal(UiSender.allowed(sender,id),false);")

if __name__=='__main__':unittest.main()
