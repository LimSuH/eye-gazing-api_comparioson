"""Common nine-point calibration in browser CSS-pixel coordinates."""

# The target is 46 px wide and has an 8 px visual glow.  A percentage-only
# inset made edge targets clip in short/small browser viewports.  Keep at least
# 48 CSS pixels while retaining the original 2.5% inset on very large screens.
CALIBRATION_MIN_INSET_PX = 48.0
CALIBRATION_EDGE_RATIO = 0.025
CALIBRATION_LAYOUT = (
    ('center','center'), ('left','top'), ('right','top'),
    ('right','bottom'), ('left','bottom'), ('center','top'),
    ('right','center'), ('center','bottom'), ('left','center'),
)
SETTLE_MS = 800


def calibration_targets(width, height):
    """Return the exact nine displayed/trained locations in CSS pixels."""
    if any(type(value) is not int or value < 200 for value in (width, height)):
        raise ValueError('Calibration viewport must be at least 200 x 200 CSS pixels')
    inset_x = max(CALIBRATION_MIN_INSET_PX, width*CALIBRATION_EDGE_RATIO)
    inset_y = max(CALIBRATION_MIN_INSET_PX, height*CALIBRATION_EDGE_RATIO)
    axes = {
        'left': inset_x, 'right': width-inset_x,
        'top': inset_y, 'bottom': height-inset_y,
        'center_x': width/2, 'center_y': height/2,
    }
    return [[axes['center_x'] if horizontal == 'center' else axes[horizontal],
             axes['center_y'] if vertical == 'center' else axes[vertical]]
            for horizontal, vertical in CALIBRATION_LAYOUT]


def config():
    return dict(protocol_id='shared-9-pixel-safe-online',
                calibration_point_count=len(CALIBRATION_LAYOUT),
                calibration_min_inset_px=CALIBRATION_MIN_INSET_PX,
                settle_ms=SETTLE_MS)
