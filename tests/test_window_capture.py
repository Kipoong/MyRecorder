import os
import unittest
from myrecorder.window_capture import exclude_overlay, WDA_EXCLUDEFROMCAPTURE


class API:
    def __init__(self):
        self.pid=os.getpid();self.valid=True;self.root=123;self.set_ok=True;self.get_ok=True
        self.actual=WDA_EXCLUDEFROMCAPTURE;self.calls=[]
    def IsWindow(self,hwnd):return self.valid
    def GetAncestor(self,hwnd,kind):return self.root
    def GetWindowThreadProcessId(self,hwnd,pid):pid._obj.value=self.pid;return 1
    def SetWindowDisplayAffinity(self,hwnd,value):self.calls.append((hwnd,value));return self.set_ok
    def GetWindowDisplayAffinity(self,hwnd,value):value._obj.value=self.actual;return self.get_ok


class CaptureExclusionTests(unittest.TestCase):
    def test_applies_and_reads_back_to_our_top_level_window(self):
        api=API();status=exclude_overlay(123,api)
        self.assertTrue(status.applied);self.assertEqual(api.calls,[(123,0x11)])
    def test_foreign_window_is_never_modified(self):
        api=API();api.pid+=100
        self.assertFalse(exclude_overlay(123,api).applied);self.assertEqual(api.calls,[])
    def test_child_or_missing_window_is_not_modified(self):
        api=API();api.root=456
        self.assertFalse(exclude_overlay(123,api).applied);self.assertEqual(api.calls,[])
        api.root=123;api.valid=False
        self.assertFalse(exclude_overlay(123,api).applied);self.assertEqual(api.calls,[])
    def test_denied_api_is_failure(self):
        api=API();api.set_ok=False
        self.assertFalse(exclude_overlay(123,api).applied)
        def failed_call(hwnd,value):raise TypeError('synthetic native failure')
        api.SetWindowDisplayAffinity=failed_call
        self.assertFalse(exclude_overlay(123,api).applied)
    def test_legacy_monitor_value_is_not_exclude_success(self):
        api=API();api.actual=1
        self.assertFalse(exclude_overlay(123,api).applied)
    def test_readback_failure_is_not_success(self):
        api=API();api.get_ok=False
        self.assertFalse(exclude_overlay(123,api).applied)


if __name__=='__main__':unittest.main()
