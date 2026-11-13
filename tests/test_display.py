from types import SimpleNamespace
import unittest
from unittest.mock import patch
from myrecorder.display import map_region, physical_region, NativeMonitor, DisplayError


class DisplayTests(unittest.TestCase):
    def test_100_percent_preserves_capture_rect(self):
        self.assertEqual(map_region((25,30,640,360),(0,0,1920,1080),(0,0,1920,1080)),(25,30,640,360))
    def test_125_percent(self):
        self.assertEqual(map_region((80,40,640,360),(0,0,1536,864),(0,0,1920,1080)),(100,50,800,450))
    def test_150_percent(self):
        self.assertEqual(map_region((100,50,400,200),(0,0,1280,720),(0,0,1920,1080)),(150,75,600,300))
    def test_mixed_dpi_negative_origin_uses_local_offsets(self):
        self.assertEqual(map_region((-1820,40,400,200),(-1920,0,1280,720),(-1920,0,1920,1080)),(-1770,60,600,300))
    def test_cross_monitor_and_invalid_coordinates_rejected(self):
        for r in [(-1,0,100,100),(0,0,0,100),(1000,0,500,400),(0,0,float('nan'),1)]:
            with self.subTest(rect=r),self.assertRaises(DisplayError): map_region(r,(0,0,1280,720),(0,0,1920,1080))
    def test_monitor_name_and_awareness_must_match(self):
        def rect(x,y,w,h): return SimpleNamespace(x=lambda:x,y=lambda:y,width=lambda:w,height=lambda:h)
        screen=SimpleNamespace(geometry=lambda:rect(0,0,1280,720),name=lambda:'EXAMPLE_DISPLAY',devicePixelRatio=lambda:1.5)
        with patch('myrecorder.display.native_monitors',return_value=[NativeMonitor('EXAMPLE_DISPLAY',(0,0,1920,1080))]),patch('myrecorder.display.dpi_awareness',return_value=2):
            self.assertEqual(physical_region(screen,rect(100,50,400,200)),(150,75,600,300))
        with patch('myrecorder.display.native_monitors',return_value=[NativeMonitor('OTHER_DISPLAY',(0,0,1920,1080))]),patch('myrecorder.display.dpi_awareness',return_value=2):
            self.assertEqual(physical_region(screen,rect(0,0,100,100)),(0,0,150,150))
        with patch('myrecorder.display.native_monitors',return_value=[NativeMonitor('EXAMPLE_DISPLAY',(0,0,1920,1080))]),patch('myrecorder.display.dpi_awareness',return_value=1):
            with self.assertRaises(DisplayError): physical_region(screen,rect(0,0,100,100))


if __name__=='__main__': unittest.main()
