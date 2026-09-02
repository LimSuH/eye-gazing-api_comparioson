"""Calibration layout checks: no browser, model, server, or camera."""
from pathlib import Path
import re
import unittest

from gaze_compare.protocol import (CALIBRATION_MIN_INSET_PX, calibration_targets,
                                   config)


ROOT = Path(__file__).resolve().parents[1]


class CalibrationLayoutTests(unittest.TestCase):
    def test_all_nine_targets_are_inside_every_supported_viewport(self):
        for width,height in ((200,200),(320,240),(800,600),(1366,768),(1920,1080),(3840,2160)):
            with self.subTest(width=width,height=height):
                targets=calibration_targets(width,height)
                self.assertEqual(len(targets),9)
                self.assertEqual(len({tuple(point) for point in targets}),9)
                for x,y in targets:
                    self.assertGreaterEqual(x,CALIBRATION_MIN_INSET_PX)
                    self.assertGreaterEqual(y,CALIBRATION_MIN_INSET_PX)
                    self.assertLessEqual(x,width-CALIBRATION_MIN_INSET_PX)
                    self.assertLessEqual(y,height-CALIBRATION_MIN_INSET_PX)

    def test_order_is_center_corners_then_edge_centers(self):
        self.assertEqual(calibration_targets(1000,800),[
            [500,400],[48,48],[952,48],[952,752],[48,752],
            [500,48],[952,400],[500,752],[48,400],
        ])

    def test_large_viewport_retains_original_edge_ratio(self):
        targets=calibration_targets(4000,3000)
        self.assertEqual(targets[1],[100,75])
        self.assertEqual(targets[3],[3900,2925])

    def test_browser_uses_server_pixel_targets_and_checks_visibility(self):
        source=(ROOT/'web/app.js').read_text(encoding='utf-8')
        self.assertIn("cfg.calibration_targets=reply.calibration_targets",source)
        self.assertIn("target:cfg.calibration_targets[pointId].slice()",source)
        self.assertIn('getBoundingClientRect()',source)
        self.assertNotIn('target[0]*viewport[0]',source)
        self.assertNotIn('target[1]*viewport[1]',source)

    def test_css_target_visual_extent_fits_the_minimum_inset_and_stays_on_top(self):
        style=(ROOT/'web/style.css').read_text(encoding='utf-8')
        size=int(re.search(r'--cal-target-size:(\d+)px',style).group(1))
        glow=int(re.search(r'box-shadow:0 0 0 (\d+)px',style).group(1))
        z=int(re.search(r'#target\{[^}]*z-index:(\d+)',style).group(1))
        hud_z=int(re.search(r'#calibrationHUD\{[^}]*z-index:(\d+)',style).group(1))
        self.assertGreaterEqual(CALIBRATION_MIN_INSET_PX,size/2+glow+8)
        self.assertGreater(z,hud_z)
        self.assertEqual(config()['calibration_point_count'],9)

    def test_invalid_viewport_is_rejected(self):
        for viewport in ((199,500),(500,199),(500.0,500),(True,500)):
            with self.assertRaises(ValueError):
                calibration_targets(*viewport)


if __name__ == '__main__':
    unittest.main()
