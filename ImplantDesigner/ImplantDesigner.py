import os
from typing import Annotated, Optional

import numpy as np

from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk
import vtkSegmentationCorePython as vtkSegmentationCore

import vtk

import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

from slicer import vtkMRMLSegmentationNode
from SegmentEditor import SegmentEditor


#
# ImplantDesigner
#


class ImplantDesigner(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("ImplantDesigner")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Cranial Implants")]
        self.parent.dependencies = []
        self.parent.contributors = ["John Doe (AnyWare Corp.)"]
        self.parent.helpText = _("""
This is an example of scripted loadable module bundled in an extension.
See more information in <a href="https://github.com/organization/projectname#ImplantDesigner">module documentation</a>.
""")
        self.parent.acknowledgementText = _("""
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")

        slicer.app.connect("startupCompleted()", registerSampleData)


#
# Register sample data sets in Sample Data module
#


def registerSampleData():
    """Add data sets to Sample Data module."""
    import SampleData

    iconsPath = os.path.join(os.path.dirname(__file__), "Resources/Icons")

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="ImplantDesigner",
        sampleName="ImplantDesigner1",
        thumbnailFileName=os.path.join(iconsPath, "ImplantDesigner1.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        fileNames="ImplantDesigner1.nrrd",
        checksums="SHA256:998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        nodeNames="ImplantDesigner1",
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="ImplantDesigner",
        sampleName="ImplantDesigner2",
        thumbnailFileName=os.path.join(iconsPath, "ImplantDesigner2.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        fileNames="ImplantDesigner2.nrrd",
        checksums="SHA256:1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        nodeNames="ImplantDesigner2",
    )


#
# ImplantDesignerParameterNode
#


@parameterNodeWrapper
class ImplantDesignerParameterNode:
    # Implant inputs
    implantSegmentation: vtkMRMLSegmentationNode
    implantSegmentID: str = ""

    # Structure inputs
    structuresSegmentation: vtkMRMLSegmentationNode
    structuresSegmentID: str = ""
    structuresPeriodicity: float = 5.0
    structuresWallThickness: float = 0.8
    structuresIntersect: bool = False

    # Legacy - kept so old scenes don't break on load
    inputSegmentation: vtkMRMLSegmentationNode
    inputSegmentID: str = ""


#
# ImplantDesignerWidget
#


class ImplantDesignerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/ImplantDesigner.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = ImplantDesignerLogic()

        #Scene observers
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        #Implant input segmentation combo box
        self.ui.ImplantSegmentationComboBox.setMRMLScene(slicer.mrmlScene)
        self.ui.ImplantSegmentationComboBox.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onImplantSegmentationChanged
        )

        #Implant segment selector widget
        self.ui.implantSegmentSelector.setMRMLScene(slicer.mrmlScene)
        self.ui.implantSegmentSelector.connect(
            "currentSegmentChanged(QString)", self.onImplantSegmentChanged
        )

        #Implant interact checkbox
        self.ui.implantInteractCheckBox.connect(
            "toggled(bool)", self.onImplantInteractToggled
        )

        #Implant buttons
        self.ui.symmetryPlaneButton.connect("clicked(bool)", self.onSymmetryPlaneButton)
        self.ui.mirrorButton.connect("clicked(bool)", self.onMirrorButton)

        #Structures input segmentation combo box
        self.ui.structuresSegmentationComboBox.setMRMLScene(slicer.mrmlScene)
        self.ui.structuresSegmentationComboBox.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onStructuresSegmentationChanged
        )

        # Structures input segment selector widget
        self.ui.structuresSegmentSelector.setMRMLScene(slicer.mrmlScene)
        self.ui.structuresSegmentSelector.connect(
            "currentSegmentChanged(QString)", self.onStructuresSegmentChanged
        )

        #Structure type combo box
        self.ui.structureTypeComboBox.clear()
        self.ui.structureTypeComboBox.addItem("Gyroid") #Supported types (Gyroid)
        #Future types can be added here:

        #Structures periodicity slider
        #Range 1-20 mm - slider 10 - 200
        self.ui.structuresPeriodicitySlider.setMinimum(10)
        self.ui.structuresPeriodicitySlider.setMaximum(200)
        self.ui.structuresPeriodicitySlider.setValue(
            int(self._periodicityDefault() * 10)
        )
        self.ui.structuresPeriodicitySlider.connect(
            "valueChanged(int)", self.onPeriodicitySliderChanged
        )

        #Structures wall thickness slider
        #Range 0.1-5 mm - slider 1 - 50
        self.ui.structuresWallSlider.setMinimum(1)
        self.ui.structuresWallSlider.setMaximum(50)
        self.ui.structuresWallSlider.setValue(
            int(self._wallThicknessDefault() * 10)
        )
        self.ui.structuresWallSlider.connect(
            "valueChanged(int)", self.onWallSliderChanged
        )

        #Structures size line edits - default 5x5x5 mm
        self.ui.structuresLengthLineEdit.setText("10")
        self.ui.structuresWidthLineEdit.setText("10")
        self.ui.structuresHeightLineEdit.setText("10")

        #Structures intersect checkbox
        self.ui.structuresIntersectCheckBox.connect(
            "toggled(bool)", self.onStructuresIntersectToggled
        )

        #Structures generate button
        self.ui.generateGyroid.connect("clicked(bool)", self.onGenerateGyroid)

        #Parameter node init
        self.initializeParameterNode()

    #helpers

    def _periodicityDefault(self):
        return 5.0

    def _wallThicknessDefault(self):
        return 0.8

    #lifecycle

    def cleanup(self) -> None:
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()

    def exit(self) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._onParameterNodeModified)

    def onSceneStartClose(self, caller, event) -> None:
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        if self.parent.isEntered:
            self.initializeParameterNode()

    #parameter node

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

        #Select first available segmentation node
        firstSeg = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")

        if firstSeg:
            if not self._parameterNode.implantSegmentation:
                self._parameterNode.implantSegmentation = firstSeg
            if not self._parameterNode.structuresSegmentation:
                self._parameterNode.structuresSegmentation = firstSeg

        #Sync selector widgets to the current parameter node values
        if self._parameterNode.implantSegmentation:
            self.ui.implantSegmentSelector.setCurrentNode(
                self._parameterNode.implantSegmentation
            )
            if not self._parameterNode.implantSegmentID:
                firstSegmentID = self._parameterNode.implantSegmentation.GetSegmentation().GetNthSegmentID(0)
                if firstSegmentID:
                    self._parameterNode.implantSegmentID = firstSegmentID

        if self._parameterNode.structuresSegmentation:
            self.ui.structuresSegmentSelector.setCurrentNode(
                self._parameterNode.structuresSegmentation
            )
            if not self._parameterNode.structuresSegmentID:
                firstSegmentID = self._parameterNode.structuresSegmentation.GetSegmentation().GetNthSegmentID(0)
                if firstSegmentID:
                    self._parameterNode.structuresSegmentID = firstSegmentID

        #Sync sliders to stored parameter values
        self.ui.structuresPeriodicitySlider.setValue(
            int(self._parameterNode.structuresPeriodicity * 10)
        )
        self.ui.structuresWallSlider.setValue(
            int(self._parameterNode.structuresWallThickness * 10)
        )

        #Sync checkboxes
        self.ui.structuresIntersectCheckBox.setChecked(
            self._parameterNode.structuresIntersect
        )

    def setParameterNode(self, inputParameterNode: Optional[ImplantDesignerParameterNode]) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._onParameterNodeModified)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._onParameterNodeModified)
            self._onParameterNodeModified()

    def _onParameterNodeModified(self, caller=None, event=None) -> None:
        implantReady = (
            self._parameterNode
            and self._parameterNode.implantSegmentation
            and self._parameterNode.implantSegmentID
        )
        structureReady = (
            self._parameterNode
            and self._parameterNode.structuresSegmentation
            and self._parameterNode.structuresSegmentID
        )

        self.ui.symmetryPlaneButton.setEnabled(bool(implantReady))
        self.ui.mirrorButton.setEnabled(bool(implantReady))
        self.ui.generateGyroid.setEnabled(bool(structureReady))

    #Implants GUI functions

    def onImplantSegmentationChanged(self, newNode) -> None:
        if self._parameterNode:
            self._parameterNode.implantSegmentation = newNode
            self.ui.implantSegmentSelector.setCurrentNode(newNode)

    def onImplantSegmentChanged(self, segmentID: str) -> None:
        if self._parameterNode:
            self._parameterNode.implantSegmentID = segmentID
            if segmentID:
                self.ui.logTextBox.append("Implant: segment selected")

    def onImplantInteractToggled(self, checked: bool) -> None:
        try:
            planeNode = slicer.util.getNode("SymmetryPlane")
        except slicer.util.MRMLNodeNotFoundException:
            if checked:
                self.ui.logTextBox.append(
                    "No symmetry plane found - create one first."
                )
            return

        displayNode = planeNode.GetDisplayNode()
        if displayNode:
            displayNode.SetHandlesInteractive(checked)
            displayNode.SetRotationHandleVisibility(checked)
            displayNode.SetTranslationHandleVisibility(checked)
            displayNode.SetScaleHandleVisibility(checked)
            self.ui.logTextBox.append(
                f"Interact handles {'enabled' if checked else 'disabled'}."
            )

    def onSymmetryPlaneButton(self) -> None:
        if not self._parameterNode.implantSegmentation or not self._parameterNode.implantSegmentID:
            self.ui.logTextBox.append("Select an implant segmentation and segment first.")
            return
        polyData = self.logic.getPolyDataFromSegmentation(
            self._parameterNode.implantSegmentation,
            self._parameterNode.implantSegmentID,
        )
        if not polyData:
            return
        centroid, normal = self.logic.getSymmetryPlane(polyData)
        planeNode = self.logic.createSymmetryPlane(centroid, normal)

        displayNode = planeNode.GetDisplayNode()
        if displayNode:
            displayNode.SetHandlesInteractive(self.ui.implantInteractCheckBox.isChecked())

        self.ui.logTextBox.append("Symmetry plane created.")

    def onMirrorButton(self) -> None:
        if not self._parameterNode.implantSegmentation or not self._parameterNode.implantSegmentID:
            self.ui.logTextBox.append("Select an implant segmentation and segment first.")
            return

        polyData = self.logic.getPolyDataFromSegmentation(
            self._parameterNode.implantSegmentation,
            self._parameterNode.implantSegmentID,
        )
        if not polyData:
            return

        try:
            planeNode = slicer.util.getNode("SymmetryPlane")
        except slicer.util.MRMLNodeNotFoundException:
            self.ui.logTextBox.append("No symmetry plane found - create one first.")
            return

        origin = [0, 0, 0]
        normal = [0, 0, 0]
        planeNode.GetOriginWorld(origin)
        planeNode.GetNormalWorld(normal)

        mirroredSkull = self.logic.mirrorSkullThroughPlane2(polyData, origin, normal)
        self.logic.createImplant(mirroredSkull, self._parameterNode.implantSegmentation)
        self.ui.logTextBox.append("Implant created from mirrored segment.")

    #Structures GUI functions

    def onStructuresSegmentationChanged(self, newNode) -> None:
        if self._parameterNode:
            self._parameterNode.structuresSegmentation = newNode
            self.ui.structuresSegmentSelector.setCurrentNode(newNode)

    def onStructuresSegmentChanged(self, segmentID: str) -> None:
        if self._parameterNode:
            self._parameterNode.structuresSegmentID = segmentID
            if segmentID:
                self.ui.logTextBox.append("Structure: segment selected")

    def onPeriodicitySliderChanged(self, sliderValue: int) -> None:
        floatValue = sliderValue / 10.0
        if self._parameterNode:
            self._parameterNode.structuresPeriodicity = floatValue
        self.ui.logTextBox.append(f"Periodicity: {floatValue:.1f} mm")

    def onWallSliderChanged(self, sliderValue: int) -> None:
        floatValue = sliderValue / 10.0
        if self._parameterNode:
            self._parameterNode.structuresWallThickness = floatValue
        self.ui.logTextBox.append(f"Wall thickness: {floatValue:.1f} mm")

    def onStructuresIntersectToggled(self, checked: bool) -> None:
        if self._parameterNode:
            self._parameterNode.structuresIntersect = checked
        self.ui.logTextBox.append(
            f"Intersect with segment: {'on' if checked else 'off'}"
        )

    def onGenerateGyroid(self) -> None:
        if not self._parameterNode.structuresSegmentation or not self._parameterNode.structuresSegmentID:
            self.ui.logTextBox.append("Select a structure segmentation and segment first.")
            return

        polyData = self.logic.getPolyDataFromSegmentation(
            self._parameterNode.structuresSegmentation,
            self._parameterNode.structuresSegmentID,
        )
        if not polyData:
            self.ui.logTextBox.append("Could not retrieve polydata from selected segment.")
            return

        period = self._parameterNode.structuresPeriodicity
        wallThickness = self._parameterNode.structuresWallThickness
        doIntersect = self._parameterNode.structuresIntersect

        b = polyData.GetBounds()
        center = [(b[0] + b[1]) / 2.0, (b[2] + b[3]) / 2.0, (b[4] + b[5]) / 2.0]
        try:
            sizeL = float(self.ui.structuresLengthLineEdit.text) / 2.0
            sizeW = float(self.ui.structuresWidthLineEdit.text) / 2.0
            sizeH = float(self.ui.structuresHeightLineEdit.text) / 2.0
        except ValueError:
            self.ui.logTextBox.append("Invalid size values - using default 5x5x5 mm.")
            sizeL = sizeW = sizeH = 5.0
        safeBounds = [
            center[0] - sizeL, center[0] + sizeL,
            center[1] - sizeW, center[1] + sizeW,
            center[2] - sizeH, center[2] + sizeH,
        ]

        self.ui.logTextBox.append(
            f"Generating Gyroid - period={period:.1f} mm, wall={wallThickness:.1f} mm ..."
        )
        slicer.app.processEvents()

        gyroidPoly = self.logic.generateGyroidMesh(
            safeBounds, period=period, wall_thickness=wallThickness
        )

        newSegNode = self.logic.createGyroidSegmentation(gyroidPoly, "Implant_Workspace")

        sourceSegmentation = self._parameterNode.structuresSegmentation.GetSegmentation()
        sourceSegment = sourceSegmentation.GetSegment(self._parameterNode.structuresSegmentID)

        if sourceSegment:
            copiedSegment = vtkSegmentationCore.vtkSegment()
            copiedSegment.DeepCopy(sourceSegment)
            newSegNode.GetSegmentation().AddSegment(copiedSegment)
            newSegNode.CreateBinaryLabelmapRepresentation()
            newSegNode.CreateClosedSurfaceRepresentation()
            self.ui.logTextBox.append("Gyroid created. Original segment copied into the same node.")
        else:
            self.ui.logTextBox.append("Could not find original segment to copy.")

        if doIntersect:
            gyroidSegmentID = newSegNode.GetSegmentation().GetNthSegmentID(0)
            self.logic.intersectGyroidWithSegment(
                newSegNode,
                gyroidSegmentID,
                self._parameterNode.structuresSegmentation,
                self._parameterNode.structuresSegmentID,
            )
            self.ui.logTextBox.append("Gyroid intersected with input segment.")


#
# ImplantDesignerLogic
#


class ImplantDesignerLogic(ScriptedLoadableModuleLogic):
    """This class should implement all the actual
    computation done by your module. The interface
    should be such that other python code can import
    this class and make use of the functionality without
    requiring an instance of the Widget.
    Uses ScriptedLoadableModuleLogic base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)

    def getParameterNode(self):
        return ImplantDesignerParameterNode(super().getParameterNode())

    def getPolyDataFromSegmentation(self, segmentation, segmentID):
        if not segmentation or not segmentID:
            print("No segmentation or segment selected")
            return None

        segmentation.CreateClosedSurfaceRepresentation()
        polyData = segmentation.GetClosedSurfaceInternalRepresentation(segmentID)
        return polyData

    def getSymmetryPlane(self, polyData):
        centroid, normal = self.getOptSymPlane(polyData, threshold=2.0)
        return centroid, normal

    def createSymmetryPlane(self, centroid, normal):
        try:
            existing = slicer.util.getNode("SymmetryPlane")
            slicer.mrmlScene.RemoveNode(existing)
        except slicer.util.MRMLNodeNotFoundException:
            pass

        planeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsPlaneNode", "SymmetryPlane")
        planeNode.SetOrigin(centroid.tolist())
        planeNode.SetNormal(normal.tolist())
        planeNode.SetSize(250, 250)
        return planeNode

    def mirrorSkullThroughPlane2(self, polyData, centroid, normal):
        """
        Mirrors input 3D model through symmetry plane.
        Creates a reflection matrix using plane's normal vector and centroid and applies it on polyData
        """
        origin = np.array(centroid)
        normal = np.array(normal)
        normal = normal / np.linalg.norm(normal)

        rfMatrix = vtk.vtkMatrix4x4()
        for i in range(3):
            for j in range(3):
                val = (1.0 if i == j else 0.0) - 2.0 * normal[i] * normal[j]
                rfMatrix.SetElement(i, j, val)

        dist = np.dot(origin, normal)
        translation = 2.0 * dist * normal
        rfMatrix.SetElement(0, 3, translation[0])
        rfMatrix.SetElement(1, 3, translation[1])
        rfMatrix.SetElement(2, 3, translation[2])

        transform = vtk.vtkTransform()
        transform.SetMatrix(rfMatrix)

        transformer = vtk.vtkTransformPolyDataFilter()
        transformer.SetInputData(polyData)
        transformer.SetTransform(transform)
        transformer.Update()

        return transformer.GetOutput()

    def createImplant(self, mirroredSide, segmentationNode):
        """
        Generates the final implant segment geometry.
        Uses Slicer Segment Editor logical operations to subtract original 
        defected skull segment from new generated mirrored segment.
        """
        segmentation = segmentationNode.GetSegmentation()
        beforeIDs = set()
        for i in range(segmentation.GetNumberOfSegments()):
            beforeIDs.add(segmentation.GetNthSegmentID(i))

        tempModelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode")
        tempModelNode.SetName("tempModel")
        tempModelNode.SetAndObservePolyData(mirroredSide)

        slicer.modules.segmentations.logic().ImportModelToSegmentationNode(tempModelNode, segmentationNode)
        slicer.mrmlScene.RemoveNode(tempModelNode)

        afterIDs = set()
        for i in range(segmentation.GetNumberOfSegments()):
            afterIDs.add(segmentation.GetNthSegmentID(i))

        newIDs = afterIDs - beforeIDs
        mirroredSegmentID = list(newIDs)[0]
        segmentation.GetSegment(mirroredSegmentID).SetName("mirroredSegment")

        originalSegmentID = segmentationNode.GetSegmentation().GetNthSegmentID(0)

        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)

        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
        segmentEditorWidget.setSegmentationNode(segmentationNode)

        segmentEditorNode.SetSelectedSegmentID(mirroredSegmentID)

        segmentEditorWidget.setActiveEffectByName("Logical operators")
        effect = segmentEditorWidget.activeEffect()
        effect.setParameter("Operation", "SUBTRACT")
        effect.setParameter("ModifierSegmentID", originalSegmentID)
        effect.self().onApply()

        slicer.mrmlScene.RemoveNode(segmentEditorNode)

        return segmentationNode

    def filterDefect(self, polyData, threshold):
        """
        Filters out defected side of the skull based on point distances from the centroid.
        Calculates Z-score for each point's distance and removes outliers
        """
        vtkPoints = polyData.GetPoints()
        numPoints = polyData.GetNumberOfPoints()
        points = np.array([vtkPoints.GetPoint(i) for i in range(numPoints)])

        centroid = points.mean(axis=0)
        distances = np.linalg.norm(points - centroid, axis=1)
        zScores = (distances - distances.mean()) / distances.std()

        healthyMask = np.abs(zScores) < threshold
        healthyPoints = points[healthyMask]

        return healthyPoints

    def getOptSymPlane(self, polyData, threshold):
        """
        Calculates suggested symmetry plane.
        Applies singular value decomposition (SVD) to find the normal vector of the symmetry plane.
        """
        healthyPoints = self.filterDefect(polyData, threshold=2.0)

        centroid = healthyPoints.mean(axis=0)
        centeredPoints = healthyPoints - centroid

        U, S, Vh = np.linalg.svd(centeredPoints, full_matrices=False)

        normal = Vh[1]

        return centroid, normal

    def intersectGyroidWithSegment(self, gyroidSegNode, gyroidSegmentID, maskSegmentationNode, maskSegmentID):
        """
        Intersects generated gyroid structure and input implant.
        Converts both segments to binary labelmaps as numpy arrays.
        Computes the logical AND operation and pushes results back to SLicer.
        """
        gyroidSegNode.CreateBinaryLabelmapRepresentation()
        maskSegmentationNode.CreateBinaryLabelmapRepresentation()

        referenceVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")

        gyroidArray = slicer.util.arrayFromSegmentBinaryLabelmap(gyroidSegNode, gyroidSegmentID, referenceVolumeNode)
        maskArray = slicer.util.arrayFromSegmentBinaryLabelmap(maskSegmentationNode, maskSegmentID, referenceVolumeNode)

        minShape = tuple(min(g, m) for g, m in zip(gyroidArray.shape, maskArray.shape))
        g = gyroidArray[:minShape[0], :minShape[1], :minShape[2]]
        m = maskArray[:minShape[0], :minShape[1], :minShape[2]]

        intersectArray = np.logical_and(g, m).astype(np.uint8)

        result = np.zeros_like(gyroidArray)
        result[:minShape[0], :minShape[1], :minShape[2]] = intersectArray

        slicer.util.updateSegmentBinaryLabelmapFromArray(result, gyroidSegNode, gyroidSegmentID, referenceVolumeNode)

        gyroidSegNode.GetSegmentation().RemoveRepresentation(
            slicer.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName()
        )
        gyroidSegNode.CreateClosedSurfaceRepresentation()

    def generateGyroidMesh(self, bounds, period=5.0, wall_thickness=0.8):
        """
        Generates a gyroid structure
        Evaluates the implicit gyroid equation
        Extracts a base surface using the marching cubes algorithm.
        Applies linear extrusion to give walls a physical thickness
        Smooths the final geometry
        """
        spacing = 0.1

        x = np.arange(bounds[0], bounds[1], spacing, dtype=np.float32)
        y = np.arange(bounds[2], bounds[3], spacing, dtype=np.float32)
        z = np.arange(bounds[4], bounds[5], spacing, dtype=np.float32)
        X, Y, Z = np.meshgrid(x, y, z, indexing='ij')

        k = (2 * np.pi) / period
        gyroid = (
            np.sin(k * X) * np.cos(k * Y)
            + np.sin(k * Y) * np.cos(k * Z)
            + np.sin(k * Z) * np.cos(k * X)
        )

        binary_gyroid = np.where(gyroid > 0, 1, 0).astype(np.uint8)

        vtk_data = numpy_to_vtk(binary_gyroid.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        imageData = vtk.vtkImageData()
        imageData.SetDimensions(len(x), len(y), len(z))
        imageData.SetSpacing(spacing, spacing, spacing)
        imageData.SetOrigin(bounds[0], bounds[2], bounds[4])
        imageData.GetPointData().SetScalars(vtk_data)

        mc = vtk.vtkDiscreteMarchingCubes()
        mc.SetInputData(imageData)
        mc.SetValue(0, 1)
        mc.Update()

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(mc.GetOutputPort())
        normals.SetFeatureAngle(60.0)
        normals.ComputePointNormalsOn()
        normals.SplittingOff()
        normals.Update()

        extrude = vtk.vtkLinearExtrusionFilter()
        extrude.SetInputConnection(normals.GetOutputPort())
        extrude.SetExtrusionTypeToNormalExtrusion()
        extrude.SetScaleFactor(wall_thickness)
        extrude.Update()

        cleaner = vtk.vtkCleanPolyData()
        cleaner.SetInputConnection(extrude.GetOutputPort())
        cleaner.Update()

        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputConnection(cleaner.GetOutputPort())
        smoother.SetNumberOfIterations(50)
        smoother.SetPassBand(0.05)
        smoother.BoundarySmoothingOn()
        smoother.Update()

        return smoother.GetOutput()

    def createGyroidSegmentation(self, polyData, name="GyroidInfill"):
        segNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segNode.SetName(name)

        segmentation = segNode.GetSegmentation()
        newSegment = slicer.vtkSegment()
        newSegment.SetName("GyroidStructure")
        newSegment.AddRepresentation(
            slicer.vtkSegmentationConverter.GetSegmentationClosedSurfaceRepresentationName(),
            polyData,
        )
        segmentation.AddSegment(newSegment)

        segNode.CreateBinaryLabelmapRepresentation()
        segNode.CreateClosedSurfaceRepresentation()

        return segNode

#
# ImplantDesignerTest
#


class ImplantDesignerTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_ImplantDesigner1()

    def test_ImplantDesigner1(self):
        self.delayDisplay("Starting the test")