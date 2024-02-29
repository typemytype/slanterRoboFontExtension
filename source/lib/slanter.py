import vanilla
from defconAppKit.windows.baseWindow import BaseWindowController

from mojo.glyphPreview import GlyphPreview
from mojo.events import addObserver, removeObserver
from mojo.roboFont import CurrentGlyph, CurrentFont, RGlyph, RPoint, OpenWindow
from mojo.UI import AllSpaceCenters, CurrentGlyphWindow, SliderEditStepper, getDefault
from mojo.pens import DecomposePointPen
import mojo.drawingTools as drawingTools

from fontTools.misc.transform import Transform
from math import radians


def camelCase(txt):
    txt = ''.join(c for c in txt.title() if c.isalpha())
    return txt[0].lower() + txt[1:]


class SliderEditFloatStepper(SliderEditStepper):

    multiplier = 100.0

    def __init__(self, *args, **kwargs):
        self.useMultiplier = True
        if "useMultiplier" in kwargs:
            self.useMultiplier = kwargs["useMultiplier"]
            del kwargs["useMultiplier"]
        if self.useMultiplier:
            for key in ["value", "minValue", "maxValue"]:
                if key in kwargs:
                    kwargs[key] *= self.multiplier
        super(SliderEditFloatStepper, self).__init__(*args, **kwargs)

    def get(self):
        value = super(SliderEditFloatStepper, self).get()
        if self.useMultiplier:
            value /= self.multiplier
        return value


class SlanterController(BaseWindowController):

    title = "Slanter"

    attributes = [
        ("Skew", dict(value=7, minValue=-30, maxValue=30, useMultiplier=False)),
        ("Rotation", dict(value=0, minValue=-30, maxValue=30, useMultiplier=False)),
    ]

    def getGlyph(self, glyph, skew, rotation, addComponents=False, skipComponents=False):
        skew = radians(skew)
        rotation = radians(-rotation)

        dest = glyph.copy()

        if not addComponents:
            for component in dest.components:
                pointPen = DecomposePointPen(glyph.layer, dest.getPointPen(), component.transformation)
                component.drawPoints(pointPen)
                dest.removeComponent(component)

        for contour in list(dest):
            if contour.open:
                dest.removeContour(contour)

        if skew == 0 and rotation == 0:
            return dest

        for contour in dest:
            for bPoint in contour.bPoints:
                bcpIn = bPoint.bcpIn
                bcpOut = bPoint.bcpOut
                if bcpIn == (0, 0):
                    continue
                if bcpOut == (0, 0):
                    continue
                if bcpIn[0] == bcpOut[0] and bcpIn[1] != bcpOut[1]:
                    bPoint.anchorLabels = ["extremePoint"]
                if rotation and bcpIn[0] != bcpOut[0] and bcpIn[1] == bcpOut[1]:
                    bPoint.anchorLabels = ["extremePoint"]

        cx, cy = 0, 0
        box = glyph.bounds
        if box:
            cx = box[0] + (box[2] - box[0]) * .5
            cy = box[1] + (box[3] - box[1]) * .5

        t = Transform()
        t = t.skew(skew)
        t = t.translate(cx, cy).rotate(rotation).translate(-cx, -cy)

        if not skipComponents:
            dest.transformBy(tuple(t))
        else:
            for contour in dest.contours:
                contour.transformBy(tuple(t))

            # this seems to work !!!
            for component in dest.components:
                # get component center
                _box = glyph.layer[component.baseGlyph].bounds
                if not _box:
                    continue
                _cx = _box[0] + (_box[2] - _box[0]) * .5
                _cy = _box[1] + (_box[3] - _box[1]) * .5
                # calculate origin in relation to base glyph
                dx = cx - _cx
                dy = cy - _cy
                # create transformation matrix
                tt = Transform()
                tt = tt.skew(skew)
                tt = tt.translate(dx, dy).rotate(rotation).translate(-dx, -dy)
                # apply transformation matrix to component offset
                P = RPoint()
                P.position = component.offset
                P.transformBy(tuple(tt))
                # set component offset position
                component.offset = P.position

        dest.extremePoints(round=0)
        for contour in dest:
            for point in contour.points:
                if "extremePoint" in point.labels:
                    point.selected = True
                    point.smooth = True
                else:
                    point.selected = False
        dest.removeSelection()
        dest.round()
        return dest

    def getSelectedPoints(self, glyph):
        points = []
        if glyph:
            for contour in glyph:
                for point in contour.points:
                    points.append((point.x, point.y))
        return points

    ####

    def __init__(self):

        self._unsubscribeGlyphCallback = None
        self._holdGlyphUpdates = False

        self.w = vanilla.Window((500, 600), self.title, minSize=(500, 500))

        y = -(10 + 30 + len(self.attributes) * 30)
        self.w.preview = GlyphPreview((0, 0, -0, y))

        middleLeft = 120
        middleRight = middleLeft + 20
        right = -10

        self.w.hl = vanilla.HorizontalLine((0, y, -0, 1))

        y += 10

        for attr, kwargs in self.attributes:
            if kwargs.get("title") is None:
                txtObj = vanilla.TextBox((10, y, middleLeft, 22), "%s:" % attr, alignment="right")
                setattr(self.w, "%sText" % camelCase(attr), txtObj)
            uiElement = kwargs.get("ui", "Slider")
            if uiElement == "Slider" or uiElement is None:
                obj = SliderEditFloatStepper
            else:
                del kwargs["ui"]
                obj = getattr(vanilla, uiElement)
            obj = obj((middleRight, y - 2, -7, 22), callback=self.parametersChanged, **kwargs)
            setattr(self.w, camelCase(attr), obj)
            y += 30

        self.w.apply = vanilla.Button((-150+right, y, -10, 22), "Apply Glyph", callback=self.applyCallback)
        self.w.newFont = vanilla.Button((-150+right-10-150, y, -150+right-10, 22), "New Font", callback=self.generateFontCallback)

        self.w.showInSpaceCenter = vanilla.CheckBox((10, y, 160, 22), "Show In Space Center", callback=self.showInSpaceCenterCallback)

        addObserver(self, "currentGlyphChanged", "currentGlyphChanged")

        self.w.bind("close", self.windowClose)
        self.parametersChanged()
        self.w.open()

    def getAttributes(self):
        values = []
        for attr, kwargs in self.attributes:
            v = getattr(self.w, camelCase(attr)).get()
            values.append(v)
        return values

    def parametersChanged(self, sender=None):
        glyph = CurrentGlyph()
        attrValues = self.getAttributes()

        if glyph is None:
            outGlyph = None
        else:
            outGlyph = self.getGlyph(glyph, *attrValues)
        selectedPoints = self.getSelectedPoints(outGlyph)
        self.w.preview.setGlyph(outGlyph)
        self.w.preview.setSelection(selectedPoints)
        self.updateSpaceCenters()

    def currentGlyphChanged(self, notification):
        self.parametersChanged()
        self.subscribeGlyph(CurrentGlyph())

    def updateSpaceCenters(self):
        if self.w.showInSpaceCenter.get():
            for sp in AllSpaceCenters():
                sp.updateGlyphLineView()

    def unsubscribeGlyph(self):
        if self._unsubscribeGlyphCallback is not None:
            self._unsubscribeGlyphCallback(self, "Glyph.Changed")
            self._unsubscribeGlyphCallback = None

    def subscribeGlyph(self, glyph):
        self.unsubscribeGlyph()
        if glyph is not None:
            self._unsubscribeGlyphCallback = glyph.removeObserver
            glyph.addObserver(self, "glyphChanged", "Glyph.Changed")

    def glyphChanged(self, notification):
        if not self._holdGlyphUpdates:
            self.parametersChanged()

    def showInSpaceCenterCallback(self, sender):
        if sender.get():
            addObserver(self, "spaceCenterDraw", "spaceCenterDraw")
        else:
            removeObserver(self, "spaceCenterDraw")
        self.updateSpaceCenters()

    def spaceCenterDraw(self, notification):
        glyph = notification["glyph"]
        spaceCenter = notification["spaceCenter"]
        scale = notification["scale"]

        attrValues = self.getAttributes()
        outGlyph = self.getGlyph(glyph, *attrValues)

        inverse = spaceCenter.glyphLineView.getDisplayStates()['Inverse']
        foreground = tuple(getDefault('spaceCenterGlyphColor')) if not inverse else tuple(getDefault('spaceCenterBackgroundColor'))
        background = tuple(getDefault('spaceCenterBackgroundColor')) if not inverse else tuple(getDefault('spaceCenterGlyphColor')) 

        # cover current glyph
        drawingTools.fill(*background)
        drawingTools.stroke(*background)
        drawingTools.strokeWidth(2*scale)
        drawingTools.drawGlyph(glyph)
        drawingTools.stroke(None)

        # draw glyph preview
        drawingTools.fill(*foreground)
        drawingTools.drawGlyph(outGlyph)

    def applyCallback(self, sender):
        self._holdGlyphUpdates = True

        font = CurrentFont()
        attrValues = self.getAttributes()

        selection = []

        if CurrentGlyphWindow():
            selection = [CurrentGlyph().name]
        else:
            selection = font.selectedGlyphNames

        for name in selection:
            glyph = font[name]
            glyph.prepareUndo("Shifter")

            outGlyph = self.getGlyph(glyph, *attrValues)
            glyph.clear()
            glyph.appendGlyph(outGlyph)
            glyph.performUndo()

        self._holdGlyphUpdates = False

    def generateFontCallback(self, sender):
        progress = self.startProgress("Generating Shifters...")
        font = CurrentFont()
        outFont = RFont(showInterface=False)
        outFont.info.update(font.info.asDict())
        outFont.features.text = font.features.text

        attrValues = self.getAttributes()

        for glyph in font:
            outFont.newGlyph(glyph.name)
            outGlyph = outFont[glyph.name]
            outGlyph.width = glyph.width
            outGlyph.unicodes = glyph.unicodes
            resultGlyph = self.getGlyph(glyph, *attrValues, addComponents=True, skipComponents=True)
            outGlyph.appendGlyph(resultGlyph)
        
        outFont.glyphOrder = font.glyphOrder
        
        progress.close()

        outFont.openInterface()

    def windowClose(self, sender):
        self.unsubscribeGlyph()
        if self.w.showInSpaceCenter.get():
            removeObserver(self, "spaceCenterDraw")
            self.updateSpaceCenters()
        removeObserver(self, "currentGlyphChanged")

SlanterController()
