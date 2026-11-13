"""Synthetic coordinates only. These do not exercise Win32 or a real display."""
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from myrecorder.display import NativeMonitor, DisplayError, match_monitor, physical_region, normalize_name
from myrecorder.dpi_bootstrap import configure_dpi


def qt(name, rect, dpr=1):return {'name':name,'rect':rect,'dpr':dpr}
def rect(values):
    x,y,w,h=values
    return SimpleNamespace(x=lambda:x,y=lambda:y,width=lambda:w,height=lambda:h)
def screen(name, values, dpr=1):
    return SimpleNamespace(name=lambda:name,geometry=lambda:rect(values),devicePixelRatio=lambda:dpr)


class MatchingTests(unittest.TestCase):
    def test_standard_prefix_alias(self):
        self.assertEqual(normalize_name(r'\\.\DISPLAY1'),normalize_name('display1'))
    def test_dual_reversed_lists_same_resolution(self):
        left=qt('Example Left',(0,0,1920,1080));right=qt('Example Right',(1920,0,1920,1080))
        natives=[NativeMonitor('Native Right',right['rect']),NativeMonitor('Native Left',left['rect'])]
        self.assertEqual(match_monitor(left,[right,left],natives)[0].name,'Native Left')
        self.assertEqual(match_monitor(right,[left,right],natives)[0].name,'Native Right')
    def test_negative_origin_and_mixed_dpi(self):
        for origin in [(-1920,0),(0,-1080),(1920,0)]:
            for dpr in [1,1.25,1.5]:
                x,y=origin;q=qt('Example',(x,y,round(1920/dpr),round(1080/dpr)),dpr)
                m=NativeMonitor('Example',(x,y,1920,1080))
                self.assertEqual(match_monitor(q,[q],[m])[0],m)
    def test_identity_geometry_conflict_never_falls_back(self):
        q=qt('Example',(0,0,1920,1080))
        with self.assertRaises(DisplayError) as error:
            match_monitor(q,[q],[NativeMonitor('Example',(1920,0,1920,1080)),NativeMonitor('Other',q['rect'])])
        self.assertEqual(error.exception.code,'NAME_GEOMETRY_CONFLICT')
    def test_ambiguous_native_geometry_rejected(self):
        q=qt('Qt', (0,0,1920,1080))
        with self.assertRaises(DisplayError):match_monitor(q,[q],[NativeMonitor('A',q['rect']),NativeMonitor('B',q['rect'])])
    def test_ambiguous_qt_geometry_rejected(self):
        q=qt('Qt',(0,0,1920,1080))
        with self.assertRaises(DisplayError):match_monitor(q,[q,qt('Other',q['rect'])],[NativeMonitor('Native',q['rect'])])
    def test_wrong_scale_rejected(self):
        q=qt('Example',(0,0,1920,1080),1.25)
        with self.assertRaises(DisplayError):match_monitor(q,[q],[NativeMonitor('Example',(0,0,1920,1080))])
    def test_full_partial_and_inside_edge_log_the_physical_result(self):
        screens=[screen('Example Left',(-1920,0,1920,1080)),screen('Example Right',(0,0,1920,1080))]
        monitors=[NativeMonitor('Native Right',(0,0,1920,1080)),NativeMonitor('Native Left',(-1920,0,1920,1080))]
        for selected in screens:
            x=selected.geometry().x()
            for roi in [(x,0,1920,1080),(x+100,200,811,513),(x+7,2,1908,1028)]:
                events=Mock()
                with patch('myrecorder.display.native_monitors',return_value=monitors):
                    self.assertEqual(physical_region(selected,rect(roi),qt_screens=screens,diagnostics=events),roi)
                self.assertEqual(events.call_args.args[0],'display_mapping_ok')
                self.assertEqual(len(events.call_args.kwargs['windows_monitors']),2)
    def test_cross_monitor_failure_records_exact_condition(self):
        s=screen('Example',(0,0,1920,1080));events=Mock()
        with patch('myrecorder.display.native_monitors',return_value=[NativeMonitor('Example',(0,0,1920,1080))]):
            with self.assertRaises(DisplayError):physical_region(s,rect((1900,0,100,100)),qt_screens=[s],diagnostics=events)
        self.assertEqual(events.call_args.args[0],'display_mapping_failed')
        self.assertIn('failed_condition',events.call_args.kwargs)
    def test_removed_screen_rejected(self):
        with self.assertRaises(DisplayError) as error:physical_region(screen('A',(0,0,100,100)),rect((0,0,50,50)),qt_screens=[])
        self.assertEqual(error.exception.code,'SELECTED_SCREEN_REMOVED')
    def test_native_query_error_is_logged(self):
        s=screen('Example',(0,0,1920,1080));events=Mock()
        with patch('myrecorder.display.native_monitors',side_effect=RuntimeError('example native failure')):
            with self.assertRaises(DisplayError):physical_region(s,rect((0,0,100,100)),qt_screens=[s],diagnostics=events)
        self.assertEqual(events.call_args.kwargs['failed_condition'],'NATIVE_QUERY_FAILED')


class BootstrapTests(unittest.TestCase):
    def api(self, kind):
        return SimpleNamespace(snapshot=Mock(return_value={'process':kind,'thread':kind}),enable_v2=Mock(return_value=(False,5)))
    def test_existing_context_never_changed(self):
        for kind,level in [('system',1),('per_monitor',2),('per_monitor_v2',3)]:
            api=self.api(kind);env={}
            self.assertNotIn('error',configure_dpi(api,env))
            api.enable_v2.assert_not_called()
            self.assertEqual(env['QT_QPA_PLATFORM'],f'windows:dpiawareness={level}')
    def test_access_denied_is_not_retried(self):
        api=self.api('unaware');env={}
        state=configure_dpi(api,env)
        api.enable_v2.assert_called_once()
        self.assertEqual(state['error_code'],5)
        self.assertEqual(env['QT_QPA_PLATFORM'],'windows:dpiawareness=0')
    def test_initial_v2_enable_success(self):
        api=self.api('unaware');api.snapshot.side_effect=[{'process':'unaware','thread':'unaware'},{'process':'per_monitor_v2','thread':'per_monitor_v2'}]
        api.enable_v2.return_value=(True,0)
        env={};self.assertTrue(configure_dpi(api,env)['set_succeeded'])
        self.assertEqual(env['QT_QPA_PLATFORM'],'windows:dpiawareness=3')
    def test_preserve_other_qpa_options(self):
        env={'QT_QPA_PLATFORM':'windows:fontengine=freetype:dpiawareness=1'}
        configure_dpi(self.api('per_monitor_v2'),env)
        self.assertEqual(env['QT_QPA_PLATFORM'],'windows:fontengine=freetype:dpiawareness=3')
    def test_context_conflict_stops_without_setter(self):
        api=self.api('system');api.snapshot.return_value={'process':'system','thread':'per_monitor_v2'}
        self.assertEqual(configure_dpi(api,{})['error'],'DPI_PROCESS_THREAD_CONFLICT')
        api.enable_v2.assert_not_called()
    def test_unsupported_context_and_platform_fail(self):
        self.assertEqual(configure_dpi(self.api('gdi_scaled'),{})['error'],'DPI_CONTEXT_UNSUPPORTED')
        self.assertEqual(configure_dpi(self.api('system'),{'QT_QPA_PLATFORM':'offscreen'})['error'],'QT_PLATFORM_OVERRIDE_UNSUPPORTED')

if __name__=='__main__':unittest.main()
