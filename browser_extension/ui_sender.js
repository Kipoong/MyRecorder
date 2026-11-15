// Authorize packaged UI documents, not a string-equal URL including query/fragment.
(() => {
  function allowed(sender,id) {
    if(!sender || (sender.id && sender.id!==id) || (sender.frameId && sender.frameId!==0))return false;
    if(typeof sender.url==='string' && sender.url) {
      try {const url=new URL(sender.url);return url.protocol==='chrome-extension:' && url.hostname===id && url.pathname==='/popup.html' && !url.username && !url.password;}
      catch {return false;}
    }
    // Some popup contexts expose origin but no document URL. Never apply this to a content-script tab.
    return sender.origin===`chrome-extension://${id}` && !sender.tab;
  }
  function info(sender,id) {return {id_matches:sender?.id===id,url_present:!!sender?.url,origin_matches:sender?.origin===`chrome-extension://${id}`,has_tab:!!sender?.tab};}
  globalThis.UiSender={allowed,info};
})();
