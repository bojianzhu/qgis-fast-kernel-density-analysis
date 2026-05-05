from qgis.core import (
    QgsStyle,
    QgsRasterBandStats,
    QgsColorRampShader,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer
)

def applyPseudocolor(layer, ramp_name, invert, interp, mode, num_classes,
                     vmin=None, vmax=None):
    """
    Apply a pseudocolor renderer to a single-band raster.

    vmin/vmax: optional explicit colour-ramp bounds. When given, they override
        the per-band statistics — useful for STKDV where every time slice must
        share the same colour scale so frames are visually comparable.
    """

    if interp == 0:  # Discrete
        interpolation = QgsColorRampShader.Discrete
    elif interp == 1:  # Liner Interpolated
        interpolation = QgsColorRampShader.Interpolated
    elif interp == 2:  # Exact
        interpolation = QgsColorRampShader.Exact

    if mode == 0:  # Continuous
        shader_mode = QgsColorRampShader.Continuous
    elif mode == 1:  # Equal Interval
        shader_mode = QgsColorRampShader.EqualInterval
    elif mode == 2:  # Quantile
        shader_mode = QgsColorRampShader.Quantile
    provider = layer.dataProvider()

    if vmin is None or vmax is None:
        stats = provider.bandStatistics(1, QgsRasterBandStats.Min | QgsRasterBandStats.Max)
        if vmin is None:
            vmin = stats.minimumValue
        if vmax is None:
            vmax = stats.maximumValue

    style = QgsStyle.defaultStyle()
    ramp = style.colorRamp(ramp_name)
    if invert:
        ramp.invert()
    color_ramp = QgsColorRampShader(vmin, vmax, ramp, interpolation, shader_mode)
    if shader_mode == QgsColorRampShader.Quantile:
        color_ramp.classifyColorRamp(classes=num_classes, band=1, input=provider)
    else:
        color_ramp.classifyColorRamp(classes=num_classes)

    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(color_ramp)

    # Create a new single band pseudocolor renderer
    renderer = QgsSingleBandPseudoColorRenderer(provider, layer.type(), raster_shader)

    layer.setRenderer(renderer)
    layer.renderer().setOpacity(0.75)
    layer.triggerRepaint()