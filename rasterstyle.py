from qgis.core import Qgis, QgsStyle, QgsMapLayerType, QgsRasterBandStats, QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer

def applyPseudocolor(layer):
    ramp_name = "Reds"

    invert = False
    interp = 0
    mode = 1
    num_classes = 15

    rnd = layer.renderer()

    if interp == 0:  # Discrete
        interpolation = QgsColorRampShader.Discrete
    elif interp == 1:  # Interpolated
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
    stats = provider.bandStatistics(1, QgsRasterBandStats.Min | QgsRasterBandStats.Max)

    style = QgsStyle.defaultStyle()
    ramp = style.colorRamp(ramp_name)
    if invert:
        ramp.invert()
    color_ramp = QgsColorRampShader(stats.minimumValue, stats.maximumValue, ramp, interpolation, shader_mode)
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