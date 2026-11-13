import unittest
from myrecorder.regions import edit_region


class RegionEditTests(unittest.TestCase):
    def setUp(self):
        self.rect=(100,100,200,150);self.bounds=(0,0,1000,800)
    def test_move_preserves_size(self):
        self.assertEqual(edit_region(self.rect,35,-20,'move',self.bounds),(135,80,200,150))
    def test_move_clamps_to_monitor(self):
        self.assertEqual(edit_region(self.rect,-500,2000,'move',self.bounds),(0,650,200,150))
    def test_negative_monitor_origin(self):
        self.assertEqual(edit_region((-900,100,200,150),-500,0,'move',(-1000,0,1000,800)),(-1000,100,200,150))
    def test_southeast_resize(self):
        self.assertEqual(edit_region(self.rect,40,25,'se',self.bounds),(100,100,240,175))
    def test_northwest_resize_keeps_opposite_corner(self):
        self.assertEqual(edit_region(self.rect,-40,-25,'nw',self.bounds),(60,75,240,175))
    def test_minimum_prevents_inversion(self):
        self.assertEqual(edit_region(self.rect,1000,1000,'nw',self.bounds),(268,218,32,32))
    def test_resize_cannot_cross_monitor_edge(self):
        self.assertEqual(edit_region(self.rect,2000,2000,'se',self.bounds),(100,100,900,700))
    def test_all_eight_handles_keep_positive_inside_bounds(self):
        for mode in ('n','s','e','w','ne','nw','se','sw'):
            for dx,dy in ((1000,1000),(-1000,-1000),(20,-10)):
                x,y,w,h=edit_region(self.rect,dx,dy,mode,self.bounds)
                self.assertGreaterEqual(w,32);self.assertGreaterEqual(h,32)
                self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                self.assertLessEqual(x+w,1000);self.assertLessEqual(y+h,800)
    def test_invalid_mode_and_values_are_rejected(self):
        for mode,dx in [('unknown',1),('move',float('nan'))]:
            with self.assertRaises(ValueError):edit_region(self.rect,dx,0,mode,self.bounds)
        with self.assertRaises(ValueError):edit_region((900,0,200,100),0,0,'move',self.bounds)


if __name__=='__main__':unittest.main()
