import logging
import os
from typing import Annotated, Optional
import tempfile
import subprocess
import json
import re
import platform
import shutil

from qt import QFileDialog
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
from slicer import vtkMRMLSegmentationNode, vtkMRMLScalarVolumeNode

#
# SegmentToPrint
#


class SegmentToPrint(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("SegmentToPrint")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "3D Printing")]
        self.parent.dependencies = []
        self.parent.contributors = ["John Doe (AnyWare Corp.)"]
        self.parent.helpText = _("Automated 3D printing workflow for anatomical segmentations.")
        self.parent.acknowledgementText = _("""""")


#
# SegmentToPrintParameterNode
#


@parameterNodeWrapper
class SegmentToPrintParameterNode:

    inputSegmentation: vtkMRMLSegmentationNode
    inputSegmentID: str = ""
    outputFilePath: str = ""
    slicerPath: str = ""
    printerBrand: str = ""
    printerModel: str = ""
    nozzleSize: str = ""
    processProfilePath: str = ""
    filamentProfilePath: str = ""
    filamentType: str = ""
    supportType: str = ""
    supportStyle: str = ""
    supportsEnabled: bool = False
    buildPlateOnly: bool = False


#
# SegmentToPrintWidget
#


class SegmentToPrintWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None
        self._defaultSlicerPath = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/SegmentToPrint.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = SegmentToPrintLogic()

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        #Connect buttons
        self.ui.generateGcodeButton.connect("clicked(bool)", self.onGenerateGcodeButton)
        self.ui.outputBrowseButton.connect("clicked()", self.onBrowseOutputPath)

        #Setup input segmentation comboBox
        self.ui.inputComboBox.setMRMLScene(slicer.mrmlScene)
        self.ui.inputComboBox.connect("currentNodeChanged(vtkMRMLNode*)", self.onInputSegmentationChanged)

        self.ui.inputSegmentSelectorWidget.setMRMLScene(slicer.mrmlScene)
        self.ui.inputSegmentSelectorWidget.connect("currentSegmentChanged(QString)", self.onSegmentChanged)

        #Setup printer selection combo box
        self.printers = {
            "Bambu Lab": ["A1", "X1 Carbon", "P1S", "A1 mini", "X1E", "X1"],
            "Prusa": ["CORE One", "CORE One HF", "MK3S", "MK3.5", "MK4", "MK4S", "MK4S HF", "XL", "XL 5T", "MINI", "MINIIS"]
        }

        self.nozzleBambu = ["0.2 nozzle", "0.4 nozzle", "0.6 nozzle", "0.8 nozzle"]

        self.nozzlePrusa = {
            "CORE One": ["0.25 nozzle", "0.3 nozzle", "0.4 nozzle", "0.5 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "CORE One HF": ["0.4 nozzle", "0.5 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "MK3S": ["0.25 nozzle", "0.4 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "MK3.5": ["0.25 nozzle", "0.4 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "MK4S": ["0.25 nozzle", "0.3 nozzle", "0.4 nozzle", "0.5 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "MK4S HF": ["0.4 nozzle", "0.5 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "MK4": ["0.25 nozzle", "0.4 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "XL": ["0.25 nozzle", "0.3 nozzle", "0.4 nozzle", "0.5 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "XL 5T": ["0.25 nozzle", "0.3 nozzle", "0.4 nozzle", "0.5 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "MINI": ["0.25 nozzle", "0.4 nozzle", "0.6 nozzle", "0.8 nozzle"],
            "MINIIS": ["0.25 nozzle", "0.4 nozzle", "0.6 nozzle", "0.8 nozzle"]
        }

        brands = list(self.printers.keys())
        self.ui.printerBrandComboBox.addItems(brands)
        self.ui.printerBrandComboBox.setCurrentIndex(0)
        self.ui.printerBrandComboBox.connect("currentIndexChanged(int)", self.onPrinterBrandComboBoxChanged)

        self.ui.printerModelComboBox.connect("currentIndexChanged(int)", self.onPrinterModelComboBoxChanged)

        self.onPrinterBrandComboBoxChanged(0)

        self.ui.nozzleComboBox.addItems(self.nozzleBambu)
        self.ui.nozzleComboBox.setCurrentIndex(1)
        self.ui.nozzleComboBox.connect("currentIndexChanged(int)", self.onNozzleComboBoxChanged)

        #setup process profile combo box
        self.ui.processProfileComboBox.connect("currentIndexChanged(int)", self.onProcessProfileComboBoxChanged)

        #setup filament combobox
        self.filamentType = ["PLA", "PETG", "ABS", "ASA", "PVA", "HIPS", "PC"]
        self.ui.filamentTypeComboBox.addItems(self.filamentType)
        self.ui.filamentTypeComboBox.connect("currentIndexChanged(int)", self.onFilamentTypeComboBoxChanged)
        self.ui.filamentProfileComboBox.connect("currentIndexChanged(int)", self.onFilamentProfileComboBoxChanged)

        #setup slicer comboBox
        self.setupSlicerComboBox()
        self.ui.slicerComboBox.connect("currentIndexChanged(int)", self.onSlicerComboBoxChanged)

        #setup support settings widgets
        self.supports = {
            "Normal(auto)": ["Default", "Grid", "Snug"],
            "Tree(auto)": ["Default", "Organic", "Tree Slim", "Tree Strong", "Tree Hybrid"]
        }
        supportType = list(self.supports.keys())
        self.ui.supportTypeComboBox.addItems(supportType)
        self.ui.supportTypeComboBox.setCurrentIndex(0)

        self.ui.supportTypeComboBox.connect("currentIndexChanged(int)", self.onSupportTypeComboBoxChanged)

        self.onSupportTypeComboBoxChanged(0)

        self.ui.supportCheckBox.connect("toggled(bool)", self.onSupportsToggled)
        self.ui.buildPlateOnlyCheckBox.connect("toggled(bool)", self.onBuildPlateOnlyToggled)

        #Initialize parameter node
        self.initializeParameterNode()

        #setup default slicerPath in parameter node
        if self._parameterNode and not getattr(self._parameterNode, "slicerPath", None):
            self._parameterNode.slicerPath = getattr(self, "_defaultSlicerPath", None)

    def cleanup(self) -> None:
        self.removeObservers()

    def enter(self) -> None:
        self.initializeParameterNode()

    def exit(self) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)

    def onSceneStartClose(self, caller, event) -> None:
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

        if not self._parameterNode.inputSegmentation:
            firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode")
            if firstVolumeNode:
                self._parameterNode.inputSegmentation = firstVolumeNode

        if self._parameterNode.inputSegmentation and not self._parameterNode.inputSegmentID:
            firstID = self._parameterNode.inputSegmentation.GetSegmentation().GetNthSegmentID(0)
            if firstID:
                self._parameterNode.inputSegmentID = firstID
                self.ui.inputSegmentSelectorWidget.setCurrentSegmentID(firstID)

        #set initial printer information in parameterNode
        if not self._parameterNode.printerBrand:
            self._parameterNode.printerBrand = self.ui.printerBrandComboBox.currentText
        if not self._parameterNode.printerModel:
            self._parameterNode.printerModel = self.ui.printerModelComboBox.currentText
        if not self._parameterNode.nozzleSize:
            self._parameterNode.nozzleSize = self.ui.nozzleComboBox.currentText
        if not self._parameterNode.filamentType:
            self._parameterNode.filamentType = self.ui.filamentTypeComboBox.currentText
        if not self._parameterNode.supportStyle:
            self._parameterNode.supportStyle = self.ui.supportStyleComboBox.currentText
        if not self._parameterNode.supportType:
            self._parameterNode.supportType = self.ui.supportTypeComboBox.currentText

        printerBrand = self._parameterNode.printerBrand
        printerModel = self._parameterNode.printerModel
        nozzleSize = self._parameterNode.nozzleSize
        filamentType = self._parameterNode.filamentType

        self.updateProcessProfileComboBox(printerBrand, printerModel, nozzleSize)
        self.updateFilamentProfileComboBox(printerBrand, printerModel, nozzleSize, filamentType)

    def setParameterNode(self, inputParameterNode: Optional[SegmentToPrintParameterNode]) -> None:
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
            self._checkCanApply()

    def _checkCanApply(self, caller=None, event=None) -> None:

        if not self._parameterNode:
            self.ui.generateGcodeButton.enabled = False
            self.ui.generateGcodeButton.toolTip = _("Parameter node is not initialized")
            return

        inputReady = self._parameterNode.inputSegmentation is not None
        slicerReady = self._parameterNode.slicerPath and os.path.exists(self._parameterNode.slicerPath)
        outputReady = bool(self._parameterNode.outputFilePath)

        if inputReady and slicerReady and outputReady:
            self.ui.generateGcodeButton.enabled = True
            self.ui.generateGcodeButton.toolTip = _("Ready to generate G_code")
        else:
            self.ui.generateGcodeButton.enabled = False
            missing = []
            if not inputReady:
                missing.append("input segmentation")
            if not slicerReady:
                missing.append("Slicer CLI path")
            if not outputReady:
                missing.append("output file path")
            self.ui.generateGcodeButton.toolTip = _("Missing: " + ", ".join(missing))

    def onGenerateGcodeButton(self) -> None:
        with slicer.util.tryWithErrorDisplay(_("Failed to generate G-code."), waitCursor=True):
            self.ui.logTextBox.clear()
            self.ui.logTextBox.append("Starting G-code generation...")

            if not self._parameterNode:
                self.initializeParameterNode()

            inputSegmentation = self._parameterNode.inputSegmentation
            outputPath = self._parameterNode.outputFilePath
            slicerPath = self._parameterNode.slicerPath
            inputSegmentID = self._parameterNode.inputSegmentID

            self.ui.logTextBox.append(f"Parameter node slicerPath: {self._parameterNode.slicerPath}")
            self.ui.logTextBox.append(f"os.path.exists(slicerPath) = {os.path.exists(self._parameterNode.slicerPath)}")

            if not inputSegmentation:
                raise ValueError("No input segmentation selected.")
            if not inputSegmentID:
                raise ValueError("No input segment selected.")
            if not outputPath:
                raise ValueError("No output file path specified")
            if not slicerPath or not os.path.exists(slicerPath):
                raise ValueError("Slicer CLI path is invalid or not set")

            stlPath = self.logic.exportSegmentationToSTL(inputSegmentation, inputSegmentID)

            self.ui.logTextBox.append("")
            self.ui.logTextBox.append(f"Segment exported to temporary STL: {stlPath}")
            self.ui.logTextBox.append(f"Running external slicer CLI: {slicerPath}")

            outputDir = os.path.dirname(outputPath)
            outputFilename = os.path.basename(outputPath)
            # Strip extension from outputFilename if present, so we control it
            outputFilename = os.path.splitext(outputFilename)[0]

            originalMachineFile = self.logic.findMachineProfile(self._parameterNode.printerBrand, self._parameterNode.printerModel, self._parameterNode.nozzleSize)
            machineData = self.logic.getFlattenedJson(originalMachineFile)
            if "inherits" in machineData:
                del machineData["inherits"]

            machineFile = os.path.join(tempfile.gettempdir(), "temp_machine.json")
            with open(machineFile, "w", encoding="utf-8") as f:
                json.dump(machineData, f, indent=2)

            processFile = self.logic.createTempProcessProfile(self._parameterNode.processProfilePath, self._parameterNode.supportsEnabled, self._parameterNode.buildPlateOnly, self._parameterNode.supportType, self._parameterNode.supportStyle)

            changes = self.getFilamentValueChanges(self._parameterNode.filamentProfilePath)
            filamentFile = self.logic.createTempFilamentProfile(self._parameterNode.filamentProfilePath, changes)

            self.ui.logTextBox.append(f"Process profile selected: {processFile}")
            self.ui.logTextBox.append(f"Machine profile selected: {machineFile}")
            self.ui.logTextBox.append(f"Filament profile selected: {filamentFile}")
            self.ui.logTextBox.append("")

            # Create a temporary directory for gcode output
            sliceDataDir = os.path.join(tempfile.gettempdir(), f"SegmentToPrint_slicedata_{outputFilename}")
            os.makedirs(sliceDataDir, exist_ok=True)

            #CLI command for Orca Slicer
            #Passes all necessary inputs
            #instructs slicer to auto-orient/arrange and sets a target output
            command = [
                 slicerPath, #path to Orca Slicer
                "--arrange", "1", #automatic object placement on bed plate
                "--orient", "1", #find ideal object orientation
                "--load-settings", f"{machineFile};{processFile}", #load print profiles
                "--load-filaments", filamentFile, #nacitanie filament profiles
                "--slice", "0", #slice all plates
                "--outputdir", sliceDataDir, #output path
                "--info", #get process info
                stlPath #path to temp filament profile
            ]


            # Log the full command for debugging
            self.ui.logTextBox.append("Command: " + " ".join(command))
            self.ui.logTextBox.append("")

            result = subprocess.run(command, capture_output=True, text=True)

            self.ui.logTextBox.append(f"Return code: {result.returncode}")
            self.ui.logTextBox.append("--- STDOUT ---")
            self.ui.logTextBox.append(result.stdout if result.stdout else "(empty)")
            self.ui.logTextBox.append("--- STDERR ---")
            self.ui.logTextBox.append(result.stderr if result.stderr else "(empty)")
            self.ui.logTextBox.append("")

            # Log sliceDataDir contents regardless
            self.ui.logTextBox.append(f"sliceDataDir exists: {os.path.exists(sliceDataDir)}")
            self.ui.logTextBox.append("sliceDataDir contents:")
            for root, dirs, files in os.walk(sliceDataDir):
                for dname in dirs:
                    self.ui.logTextBox.append(f"  [dir] {os.path.join(root, dname)}")
                for fname in files:
                    self.ui.logTextBox.append(f"  {os.path.join(root, fname)}")
            self.ui.logTextBox.append("")

            # Find the generated .gcode file inside sliceDataDir and copy it to outputDir
            gcodeFound = False
            for root, dirs, files in os.walk(sliceDataDir):
                for fname in files:
                    if fname.endswith(".gcode"):
                        src = os.path.join(root, fname)
                        dst = os.path.join(outputDir, f"{outputFilename}.gcode")
                        shutil.copy2(src, dst)
                        self.ui.logTextBox.append(f"G-code saved to: {dst}")
                        gcodeFound = True
                        break
                if gcodeFound:
                    break

            if not gcodeFound:
                self.ui.logTextBox.append("WARNING: No .gcode file found in slice data output.")

            self.ui.logTextBox.append("G-Code generation finished.")
            self.ui.logTextBox.append(self._parameterNode.printerBrand)
            self.ui.logTextBox.append(self._parameterNode.printerModel)
            self.ui.logTextBox.append(self._parameterNode.nozzleSize)

            # Cleanup temp files
            if os.path.exists(filamentFile) and "temp_filament" in filamentFile:
                os.remove(filamentFile)
            if os.path.exists(processFile) and "temp_process" in processFile:
                os.remove(processFile)
            if os.path.exists(machineFile) and "temp_machine" in machineFile:
                os.remove(machineFile)
            shutil.rmtree(sliceDataDir, ignore_errors=True)

    def onInputSegmentationChanged(self, newSegmentation) -> None:
        if self._parameterNode:
            self._parameterNode.inputSegmentation = newSegmentation
            if newSegmentation:
                firstID = newSegmentation.GetSegmentation().GetNthSegmentID(0)
                self._parameterNode.inputSegmentID = firstID if firstID else ""
                if firstID:
                    self.ui.inputSegmentSelectorWidget.setCurrentSegmentID(firstID)

    def onSegmentChanged(self, segmentID) -> None:
        if self._parameterNode:
            self._parameterNode.inputSegmentID = segmentID

    def onBrowseOutputPath(self) -> None:
        filePath = QFileDialog.getSaveFileName(
            None,
            "Select output file",
            "",
            "G-code files"
        )
        if filePath:
            self.ui.outputPathLineEdit.setText(filePath)
            if self._parameterNode:
                self._parameterNode.outputFilePath = filePath

    def setupSlicerComboBox(self) -> None:
        defaultPaths = []

        system = platform.system()

        if system == "Darwin":
            defaultPaths.append("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer")
        elif system == "Windows":
            defaultPaths.extend([r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
                                  r"C:\Program Files\OrcaSlicer\OrcaSlicer.exe"])

        existingPaths = []
        for path in defaultPaths:
            if os.path.exists(path):
                existingPaths.append(path)

        self.ui.slicerComboBox.blockSignals(True)
        self.ui.slicerComboBox.clear()

        if existingPaths:
            self.ui.slicerComboBox.addItem("Orca Slicer", existingPaths[0])
            self._defaultSlicerPath = existingPaths[0]

            if self._parameterNode:
                self._parameterNode.slicerPath = existingPaths[0]
        else:
            self.ui.slicerComboBox.addItem("Select Slicer...", None)
            self._defaultSlicerPath = None

            # Show warning with download link if OrcaSlicer is not found
            import webbrowser
            downloadUrl = "https://github.com/SoftFever/OrcaSlicer/releases/tag/v2.3.1"
            result = slicer.util.confirmYesNoDisplay(
                "OrcaSlicer was not found on this system.\n\n"
                "OrcaSlicer is required to generate G-code.\n\n"
                "Would you like to open the OrcaSlicer download page?",
                windowTitle="OrcaSlicer Not Found"
            )
            if result:
                webbrowser.open(downloadUrl)

        self.ui.slicerComboBox.blockSignals(False)

        try:
            self.ui.slicerBrowseButton.disconnect("clicked(bool)")
        except Exception:
            pass
        self.ui.slicerBrowseButton.connect("clicked(bool)", self.onBrowseSlicer)

    def onBrowseSlicer(self) -> None:
        filePath = QFileDialog.getOpenFileName(
            None,
            "Select Slicer",
            "",
            "Executable files (*.exe *.app);;All Files (*)"
        )

        if isinstance(filePath, tuple):
            filePath = filePath[0]

        if filePath and filePath != "":
            #automatic correction for mac if .app file is selected
            if platform.system() == "Darwin" and filePath.endswith(".app"):
                potentialExec = os.path.join(filePath, "Contents", "MacOS", "OrcaSlicer")
                if os.path.exists(potentialExec):
                    filePath = potentialExec
            
            self.ui.slicerComboBox.blockSignals(True)
            self.ui.slicerComboBox.clear()
            self.ui.slicerComboBox.addItem(os.path.basename(filePath), filePath)
            self.ui.slicerComboBox.blockSignals(False)

            if self._parameterNode:
                self._parameterNode.slicerPath = filePath
            else:
                self._defaultSlicerPath = filePath

            self._checkCanApply()

    def onSlicerComboBoxChanged(self, index):
        if index < 0:
            return

        selectedPath = self.ui.slicerComboBox.itemData(index)

        if isinstance(selectedPath, (list, tuple)):
            if selectedPath:
                selectedPath = selectedPath[0]
            else:
                selectedPath = None

        if selectedPath:
            if self._parameterNode:
                self._parameterNode.slicerPath = selectedPath
            else:
                self._defaultSlicerPath = selectedPath

        self._checkCanApply()

    def onPrinterBrandComboBoxChanged(self, index) -> None:
        printerBrand = self.ui.printerBrandComboBox.currentText
        printerModel = self.printers.get(printerBrand, [])
        nozzleSize = self.ui.nozzleComboBox.currentText
        filamentType = self.ui.filamentTypeComboBox.currentText

        if printerBrand:
            if self._parameterNode:
                self._parameterNode.printerBrand = printerBrand

        modelComboBox = self.ui.printerModelComboBox
        modelComboBox.blockSignals(True)
        modelComboBox.clear()
        modelComboBox.addItems(printerModel)

        if printerModel:
            modelComboBox.setCurrentIndex(0)
        modelComboBox.blockSignals(False)

        self.updateProcessProfileComboBox(printerBrand, printerModel[0], nozzleSize)
        self.updateFilamentProfileComboBox(printerBrand, printerModel[0], nozzleSize, filamentType)
        self.updateNozzleComboBox(printerBrand, printerModel)

    def onPrinterModelComboBoxChanged(self, index) -> None:
        printerModel = self.ui.printerModelComboBox.currentText
        nozzleSize = self.ui.nozzleComboBox.currentText
        printerBrand = self.ui.printerBrandComboBox.currentText
        filamentType = self.ui.filamentTypeComboBox.currentText

        if self._parameterNode:
            self._parameterNode.printerModel = printerModel

        self.updateProcessProfileComboBox(printerBrand, printerModel, nozzleSize)
        self.updateFilamentProfileComboBox(printerBrand, printerModel, nozzleSize, filamentType)
        self.updateNozzleComboBox(printerBrand, printerModel)

    def onNozzleComboBoxChanged(self, index) -> None:
        printerModel = self.ui.printerModelComboBox.currentText
        nozzleSize = self.ui.nozzleComboBox.currentText
        printerBrand = self.ui.printerBrandComboBox.currentText
        filamentType = self.ui.filamentTypeComboBox.currentText

        if self._parameterNode:
            self._parameterNode.nozzleSize = nozzleSize

        self.updateProcessProfileComboBox(printerBrand, printerModel, nozzleSize)
        self.updateFilamentProfileComboBox(printerBrand, printerModel, nozzleSize, filamentType)

    def onProcessProfileComboBoxChanged(self, index) -> None:
        printerBrand = self.ui.printerBrandComboBox.currentText
        processProfile = self.ui.processProfileComboBox.currentText
        currentDir = os.path.dirname(__file__)

        if printerBrand == "Bambu Lab":
            printerBrandDir = "BBL"
        else:
            printerBrandDir = printerBrand

        processDir = os.path.join(currentDir, "Resources", "Profiles", printerBrandDir, "process")

        if self._parameterNode:
            processProfilePath = os.path.join(processDir, processProfile)
            if os.path.exists(processProfilePath):
                self._parameterNode.processProfilePath = processProfilePath

    def updateNozzleComboBox(self, printerBrand, printerModel):
        self.ui.nozzleComboBox.clear()

        if printerBrand == "Bambu Lab":
            self.ui.nozzleComboBox.addItems(self.nozzleBambu)
        elif printerBrand == "Prusa":
            self.ui.nozzleComboBox.addItems(self.nozzlePrusa[printerModel])

    def updateProcessProfileComboBox(self, printerBrand, printerModel, nozzleSize):
        processProfile = self.logic.findProcessProfile(printerBrand, printerModel, nozzleSize)

        processComboBox = self.ui.processProfileComboBox
        processComboBox.blockSignals(True)
        processComboBox.clear()
        processComboBox.addItems(processProfile)

        if processProfile:
            processComboBox.setCurrentIndex(0)
            self.onProcessProfileComboBoxChanged(None)
        processComboBox.blockSignals(False)

    def onFilamentProfileComboBoxChanged(self, index) -> None:
        printerBrand = self.ui.printerBrandComboBox.currentText
        filamentProfile = self.ui.filamentProfileComboBox.currentText
        currentDir = os.path.dirname(__file__)

        if printerBrand == "Bambu Lab":
            printerBrandDir = "BBL"
        else:
            printerBrandDir = printerBrand

        filamentDir = os.path.join(currentDir, "Resources", "Profiles", printerBrandDir, "filament")

        if self._parameterNode:
            filamentProfilePath = os.path.join(filamentDir, filamentProfile)
            if os.path.exists(filamentProfilePath):
                self._parameterNode.filamentProfilePath = filamentProfilePath

        self.loadFilamentValues()

    def updateFilamentProfileComboBox(self, printerBrand, printerModel, nozzleSize, filamentType) -> None:
        filamentProfile = self.logic.findFilamentProfile(printerBrand, printerModel, nozzleSize, filamentType)

        filamentComboBox = self.ui.filamentProfileComboBox
        filamentComboBox.blockSignals(True)
        filamentComboBox.clear()
        filamentComboBox.addItems(filamentProfile)

        if filamentProfile:
            filamentComboBox.setCurrentIndex(0)
            self.onFilamentProfileComboBoxChanged(None)
        filamentComboBox.blockSignals(False)

    def onFilamentTypeComboBoxChanged(self, index) -> None:
        printerModel = self.ui.printerModelComboBox.currentText
        nozzleSize = self.ui.nozzleComboBox.currentText
        printerBrand = self.ui.printerBrandComboBox.currentText
        filamentType = self.ui.filamentTypeComboBox.currentText

        if self._parameterNode:
            self._parameterNode.filamentType = filamentType

        self.updateFilamentProfileComboBox(printerBrand, printerModel, nozzleSize, filamentType)

    def loadFilamentValues(self):
        filamentFilePath = self._parameterNode.filamentProfilePath
        if not filamentFilePath:
            return

        values = {
            "nozzle_temperature": self.ui.nozzleTempLineEdit,
            "nozzle_temperature_initial_layer": self.ui.initialNozzleTempLineEdit,
            "hot_plate_temp": self.ui.bedTempLineEdit,
            "hot_plate_temp_initial_layer": self.ui.initialBedTempLineEdit,
            "filament_flow_ratio": self.ui.flowRatioLineEdit,
            "fan_max_speed": self.ui.fanSpeedLineEdit
        }

        for key, lineEdit in values.items():
            value = self.logic.getFilamentProfileValues(filamentFilePath, key)
            if value:
                lineEdit.setText(str(value[0]))

    def getFilamentValueChanges(self, filamentFilePath):
        changes = {}

        values = {
            "nozzle_temperature": self.ui.nozzleTempLineEdit.text,
            "nozzle_temperature_initial_layer": self.ui.initialNozzleTempLineEdit.text,
            "hot_plate_temp": self.ui.bedTempLineEdit.text,
            "hot_plate_temp_initial_layer": self.ui.initialBedTempLineEdit.text,
            "filament_flow_ratio": self.ui.flowRatioLineEdit.text,
            "fan_max_speed": self.ui.fanSpeedLineEdit.text
        }

        for key, value in values.items():
            if value:
                if not value.strip():
                    continue
                origValue = self.logic.getFilamentProfileValues(filamentFilePath, key)
                if origValue is None or not origValue or value != str(origValue[0]):
                    changes[key] = value

        return changes

    def onSupportTypeComboBoxChanged(self, index) -> None:
        supportType = self.ui.supportTypeComboBox.currentText
        supportStyle = self.supports.get(supportType, [])

        if supportType:
            if self._parameterNode:
                self._parameterNode.supportType = supportType

        styleComboBox = self.ui.supportStyleComboBox
        styleComboBox.blockSignals(True)
        styleComboBox.clear()
        styleComboBox.addItems(supportStyle)

        if supportStyle:
            styleComboBox.setCurrentIndex(0)
        styleComboBox.blockSignals(False)

    def onSupportsToggled(self, checked) -> None:
        self._parameterNode.supportsEnabled = checked
        self.ui.logTextBox.append(f"Supports Enabled: {self._parameterNode.supportsEnabled}")

    def onBuildPlateOnlyToggled(self, checked) -> None:
        self._parameterNode.buildPlateOnly = checked
        self.ui.logTextBox.append(f"Supports on build plate only: {self._parameterNode.buildPlateOnly}")


#
# SegmentToPrintLogic
#


class SegmentToPrintLogic(ScriptedLoadableModuleLogic):
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
        return SegmentToPrintParameterNode(super().getParameterNode())

    def exportSegmentationToSTL(self, segmentationNode, segmentID) -> str:
        """
        Exports selected 3D Slicer segment into a temporary STL file.
        This step is required because external Orca Slicer engine needs a 3D model file as an input argument for slicing.

        Return:
            String path to the generated temporary STL file
        """
        if not segmentationNode or not segmentID:
            raise ValueError("Segmentation node is invalid")

        segmentationNode.CreateClosedSurfaceRepresentation()

        tempDir = tempfile.mkdtemp(prefix="SegmentToPrint_")

        segmentIDs = vtk.vtkStringArray()
        segmentIDs.InsertNextValue(segmentID)

        success = slicer.modules.segmentations.logic().ExportSegmentsClosedSurfaceRepresentationToFiles(
            tempDir,
            segmentationNode,
            segmentIDs,
            "Closed surface",
            "STL",
            True,
            1.0,
        )

        if not success:
            raise RuntimeError(f"Failed to export segmentation {segmentationNode.GetName()} to STL")

        stlFiles = []
        for f in os.listdir(tempDir):
            if f.lower().endswith(".stl"):
                stlFiles.append(f)

        if stlFiles:
            return os.path.join(tempDir, stlFiles[0])
        else:
            raise RuntimeError(f"No STL file created in {tempDir}")

    def findProcessProfile(self, printerBrand, printerModel, nozzle):
        """
        Searches extension's resource directory for a matching JSON process profile.
        Uses regex to match printer names and nozzle sizes.
        """
        currentDir = os.path.dirname(__file__)

        if printerBrand == "Bambu Lab":
            printerBrandDir = "BBL"
        else:
            printerBrandDir = printerBrand

        processDir = os.path.join(currentDir, "Resources", "Profiles", printerBrandDir, "process")

        if not os.path.exists(processDir):
            return []

        compatibleProfile = []

        fullPrinterName = f"{printerBrand} {printerModel} {nozzle}"

        for filename in os.listdir(processDir):
            if filename.endswith(".json"):
                filePath = os.path.join(processDir, filename)
                try:
                    with open(filePath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                if fullPrinterName in data.get("compatible_printers", []):
                    compatibleProfile.append(filename)

        if compatibleProfile == []:
            #fallback search using regex
            printerModelRegex = rf"{re.escape(printerModel)}(?![A-Za-z0-9])"
            nozzleNumber = nozzle.replace(" nozzle", "")
            nozzleNumberRegex = rf"{re.escape(nozzleNumber)}(?![A-Za-z0-9])"

            for filename in os.listdir(processDir):
                if filename.endswith(".json"):
                    if re.search(printerModelRegex, filename):
                        if nozzle in filename.lower():
                            compatibleProfile.append(filename)
                        elif re.search(nozzleNumberRegex, filename):
                            compatibleProfile.append(filename)
                    elif re.search(rf"HF{nozzleNumberRegex}", filename):
                        compatibleProfile.append(filename)

        return compatibleProfile

    def findMachineProfile(self, printerBrand, printerModel, nozzle):
        currentDir = os.path.dirname(__file__)

        if printerBrand == "Bambu Lab":
            printerBrandDir = "BBL"
        else:
            printerBrandDir = printerBrand

        machineDir = os.path.join(currentDir, "Resources", "Profiles", printerBrandDir, "machine")

        if not os.path.exists(machineDir):
            return []

        printerModelRegex = rf"{re.escape(printerModel)}($| \d)"

        for filename in os.listdir(machineDir):
            if filename.endswith(".json"):
                if re.search(printerModelRegex, filename):
                    if nozzle in filename.lower():
                        machineProfile = filename

        machineProfilePath = os.path.join(machineDir, machineProfile)

        return machineProfilePath

    def findFilamentProfile(self, printerBrand, printerModel, nozzleSize, filamentType):
        currentDir = os.path.dirname(__file__)

        if printerBrand == "Bambu Lab":
            printerBrandDir = "BBL"
        else:
            printerBrandDir = printerBrand

        filamentDir = os.path.join(currentDir, "Resources", "Profiles", printerBrandDir, "filament")

        if not os.path.exists(filamentDir):
            return []

        compatibleProfile = []

        fullPrinterName = f"{printerBrand} {printerModel} {nozzleSize}"

        for filename in os.listdir(filamentDir):
            if filename.endswith(".json") and filamentType in filename:
                filePath = os.path.join(filamentDir, filename)
                try:
                    with open(filePath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                if fullPrinterName in data.get("compatible_printers", []):
                    compatibleProfile.append(filename)

        return compatibleProfile

    def getFilamentProfileValues(self, filamentFilePath, key, visited=None):
        """
        Recursively extract a specific parameter value from a filament JSON profile.
        If the value is not found in the current file it follows the "inherits" key.
        Used to fill out parameters in GUI.
        """
        if visited is None:
            visited = set()

        if filamentFilePath in visited:
            return None
        visited.add(filamentFilePath)

        try:
            with open(filamentFilePath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        if key in data:
            return data[key]
        else:
            if "inherits" in data:
                baseFile = data["inherits"]
                basePath = os.path.join(os.path.dirname(filamentFilePath), baseFile + ".json")
                if os.path.exists(basePath):
                    return self.getFilamentProfileValues(basePath, key, visited)

    def createTempProcessProfile(self, processFilePath, supportsEnabled, buildPlateOnly, supportType, supportStyle):
        """
        Generates a flattened JSON process profile in the system's temp directory.
        This is necessary because Orca Slicer CLI can't resolve inheretance from CLI arguments
        """
        fullData = self.getFlattenedJson(processFilePath)

        fullData["enable_support"] = str(int(supportsEnabled))
        fullData["support_on_build_plate_only"] = str(int(buildPlateOnly))
        fullData["support_type"] = supportType.replace(" ", "_").lower()
        fullData["support_style"] = supportStyle.replace(" ", "_").lower()

        if "inherits" in fullData:
            del fullData["inherits"]

        fullData["name"] = "Process_Standalone"
        fullData["from"] = "user"
        fullData["instantiation"] = "true"

        tempFilePath = os.path.join(tempfile.gettempdir(), "temp_process.json")
        with open(tempFilePath, "w", encoding="utf-8") as f:
            json.dump(fullData, f, indent=2)
        return tempFilePath

    def createTempFilamentProfile(self, filamentFilePath, changes):
        fullData = self.getFlattenedJson(filamentFilePath)

        for key, value in changes.items():
            fullData[key] = [str(value)]

        if "inherits" in fullData:
            del fullData["inherits"]

        fullData["name"] = "Filament_Standalone"

        tempFilePath = os.path.join(tempfile.gettempdir(), "temp_filament.json")

        with open(tempFilePath, "w", encoding="utf-8") as f:
            json.dump(fullData, f, indent=2)
        return tempFilePath

    def getFlattenedJson(self, filePath, visited=None):
        """
        Recursively reads and merges a JSON profile with it's parent profiles to create a single file containing all parameters.
        """
        if visited is None:
            visited = set()

        if not os.path.exists(filePath):
            return {}

        if filePath in visited:
            return {}
        visited.add(filePath)

        with open(filePath, "r", encoding="utf-8") as f:
            currentData = json.load(f)

        if "inherits" in currentData and currentData["inherits"]:
            parentName = currentData["inherits"]
            parentPath = os.path.join(os.path.dirname(filePath), parentName + ".json")

            if os.path.exists(parentPath):
                combinedData = self.getFlattenedJson(parentPath, visited)
                combinedData.update(currentData)
                return combinedData

        return currentData


#
# SegmentToPrintTest
#


class SegmentToPrintTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_SegmentToPrint1()

    def test_SegmentToPrint1(self):
        self.delayDisplay("Starting the test")

        logic = SegmentToPrintLogic()

#TODO: Change whole test class