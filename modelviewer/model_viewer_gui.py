# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'model_viewer_gui.ui'
##
## Created by: Qt User Interface Compiler version 6.9.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QListView, QMainWindow,
    QMenu, QMenuBar, QScrollArea, QSizePolicy,
    QSlider, QSpacerItem, QSpinBox, QSplitter,
    QStatusBar, QVBoxLayout, QWidget)

class Ui_ModelViewerUI(object):
    def setupUi(self, ModelViewerUI):
        if not ModelViewerUI.objectName():
            ModelViewerUI.setObjectName(u"ModelViewerUI")
        ModelViewerUI.resize(1500, 750)
        self.openFolderAction = QAction(ModelViewerUI)
        self.openFolderAction.setObjectName(u"openFolderAction")
        self.cropAction = QAction(ModelViewerUI)
        self.cropAction.setObjectName(u"cropAction")
        self.resetCropAction = QAction(ModelViewerUI)
        self.resetCropAction.setObjectName(u"resetCropAction")
        self.detectFishAction = QAction(ModelViewerUI)
        self.detectFishAction.setObjectName(u"detectFishAction")
        self.centralWidget = QWidget(ModelViewerUI)
        self.centralWidget.setObjectName(u"centralWidget")
        self.mainLayout = QHBoxLayout(self.centralWidget)
        self.mainLayout.setObjectName(u"mainLayout")
        self.splitter = QSplitter(self.centralWidget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.imageListView = QListView(self.splitter)
        self.imageListView.setObjectName(u"imageListView")
        self.splitter.addWidget(self.imageListView)
        self.imageLabel = QLabel(self.splitter)
        self.imageLabel.setObjectName(u"imageLabel")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(2)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.imageLabel.sizePolicy().hasHeightForWidth())
        self.imageLabel.setSizePolicy(sizePolicy)
        self.imageLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.splitter.addWidget(self.imageLabel)
        self.rightSidewidget = QWidget(self.splitter)
        self.rightSidewidget.setObjectName(u"rightSidewidget")
        self.verticalLayout = QVBoxLayout(self.rightSidewidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.modelGroupBox = QGroupBox(self.rightSidewidget)
        self.modelGroupBox.setObjectName(u"modelGroupBox")
        self.modelGroupBox.setEnabled(True)
        self.gridLayout_2 = QGridLayout(self.modelGroupBox)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.confidenceSpinBox = QSpinBox(self.modelGroupBox)
        self.confidenceSpinBox.setObjectName(u"confidenceSpinBox")
        self.confidenceSpinBox.setMaximum(100)
        self.confidenceSpinBox.setValue(75)

        self.gridLayout_2.addWidget(self.confidenceSpinBox, 1, 2, 1, 1)

        self.nmsSpinBox = QSpinBox(self.modelGroupBox)
        self.nmsSpinBox.setObjectName(u"nmsSpinBox")
        self.nmsSpinBox.setMaximum(100)
        self.nmsSpinBox.setValue(45)

        self.gridLayout_2.addWidget(self.nmsSpinBox, 2, 2, 1, 1)

        self.nmsLabel = QLabel(self.modelGroupBox)
        self.nmsLabel.setObjectName(u"nmsLabel")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.nmsLabel.sizePolicy().hasHeightForWidth())
        self.nmsLabel.setSizePolicy(sizePolicy1)

        self.gridLayout_2.addWidget(self.nmsLabel, 2, 0, 1, 1)

        self.confidenceSlider = QSlider(self.modelGroupBox)
        self.confidenceSlider.setObjectName(u"confidenceSlider")
        self.confidenceSlider.setEnabled(True)
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(1)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.confidenceSlider.sizePolicy().hasHeightForWidth())
        self.confidenceSlider.setSizePolicy(sizePolicy2)
        self.confidenceSlider.setMaximum(100)
        self.confidenceSlider.setSingleStep(10)
        self.confidenceSlider.setSliderPosition(75)
        self.confidenceSlider.setOrientation(Qt.Orientation.Horizontal)
        self.confidenceSlider.setTickPosition(QSlider.TickPosition.NoTicks)

        self.gridLayout_2.addWidget(self.confidenceSlider, 1, 1, 1, 1)

        self.nmsSlider = QSlider(self.modelGroupBox)
        self.nmsSlider.setObjectName(u"nmsSlider")
        self.nmsSlider.setEnabled(True)
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.nmsSlider.sizePolicy().hasHeightForWidth())
        self.nmsSlider.setSizePolicy(sizePolicy3)
        self.nmsSlider.setMaximum(100)
        self.nmsSlider.setSingleStep(10)
        self.nmsSlider.setValue(45)
        self.nmsSlider.setSliderPosition(45)
        self.nmsSlider.setOrientation(Qt.Orientation.Horizontal)
        self.nmsSlider.setTickPosition(QSlider.TickPosition.NoTicks)

        self.gridLayout_2.addWidget(self.nmsSlider, 2, 1, 1, 1)

        self.modelSelectComboBox = QComboBox(self.modelGroupBox)
        self.modelSelectComboBox.setObjectName(u"modelSelectComboBox")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.modelSelectComboBox.sizePolicy().hasHeightForWidth())
        self.modelSelectComboBox.setSizePolicy(sizePolicy4)

        self.gridLayout_2.addWidget(self.modelSelectComboBox, 0, 0, 1, 3)

        self.confidenceLabel = QLabel(self.modelGroupBox)
        self.confidenceLabel.setObjectName(u"confidenceLabel")

        self.gridLayout_2.addWidget(self.confidenceLabel, 1, 0, 1, 1)

        self.detectionsLabel = QLabel(self.modelGroupBox)
        self.detectionsLabel.setObjectName(u"detectionsLabel")

        self.gridLayout_2.addWidget(self.detectionsLabel, 3, 0, 1, 2)

        self.numDetectionsLabel = QLabel(self.modelGroupBox)
        self.numDetectionsLabel.setObjectName(u"numDetectionsLabel")
        self.numDetectionsLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.numDetectionsLabel.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse|Qt.TextInteractionFlag.TextSelectableByMouse)

        self.gridLayout_2.addWidget(self.numDetectionsLabel, 3, 2, 1, 1)


        self.verticalLayout.addWidget(self.modelGroupBox)

        self.imageInfoGroupBox = QGroupBox(self.rightSidewidget)
        self.imageInfoGroupBox.setObjectName(u"imageInfoGroupBox")
        self.verticalLayout_2 = QVBoxLayout(self.imageInfoGroupBox)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.imageInfoLabel = QLabel(self.imageInfoGroupBox)
        self.imageInfoLabel.setObjectName(u"imageInfoLabel")

        self.verticalLayout_2.addWidget(self.imageInfoLabel)


        self.verticalLayout.addWidget(self.imageInfoGroupBox)

        self.imageExifGroupBox = QGroupBox(self.rightSidewidget)
        self.imageExifGroupBox.setObjectName(u"imageExifGroupBox")
        self.horizontalLayout_2 = QHBoxLayout(self.imageExifGroupBox)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.scrollArea = QScrollArea(self.imageExifGroupBox)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents_2 = QWidget()
        self.scrollAreaWidgetContents_2.setObjectName(u"scrollAreaWidgetContents_2")
        self.scrollAreaWidgetContents_2.setGeometry(QRect(0, 0, 212, 167))
        self.horizontalLayout = QHBoxLayout(self.scrollAreaWidgetContents_2)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.imageExifLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.imageExifLabel.setObjectName(u"imageExifLabel")

        self.horizontalLayout.addWidget(self.imageExifLabel)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents_2)

        self.horizontalLayout_2.addWidget(self.scrollArea)


        self.verticalLayout.addWidget(self.imageExifGroupBox)

        self.rightSideVerticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout.addItem(self.rightSideVerticalSpacer)

        self.splitter.addWidget(self.rightSidewidget)

        self.mainLayout.addWidget(self.splitter)

        ModelViewerUI.setCentralWidget(self.centralWidget)
        self.menuBar = QMenuBar(ModelViewerUI)
        self.menuBar.setObjectName(u"menuBar")
        self.menuBar.setGeometry(QRect(0, 0, 1500, 24))
        self.menuFile = QMenu(self.menuBar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuEdit = QMenu(self.menuBar)
        self.menuEdit.setObjectName(u"menuEdit")
        ModelViewerUI.setMenuBar(self.menuBar)
        self.statusBar = QStatusBar(ModelViewerUI)
        self.statusBar.setObjectName(u"statusBar")
        ModelViewerUI.setStatusBar(self.statusBar)

        self.menuBar.addAction(self.menuFile.menuAction())
        self.menuBar.addAction(self.menuEdit.menuAction())
        self.menuFile.addAction(self.openFolderAction)
        self.menuEdit.addAction(self.cropAction)
        self.menuEdit.addAction(self.resetCropAction)
        self.menuEdit.addAction(self.detectFishAction)

        self.retranslateUi(ModelViewerUI)
        self.confidenceSpinBox.valueChanged.connect(self.confidenceSlider.setValue)
        self.nmsSpinBox.valueChanged.connect(self.nmsSlider.setValue)
        self.confidenceSlider.valueChanged.connect(self.confidenceSpinBox.setValue)
        self.nmsSlider.valueChanged.connect(self.nmsSpinBox.setValue)

        QMetaObject.connectSlotsByName(ModelViewerUI)
    # setupUi

    def retranslateUi(self, ModelViewerUI):
        ModelViewerUI.setWindowTitle(QCoreApplication.translate("ModelViewerUI", u"Fish Model Viewer", None))
        self.openFolderAction.setText(QCoreApplication.translate("ModelViewerUI", u"Open Folder...", None))
#if QT_CONFIG(shortcut)
        self.openFolderAction.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+O", None))
#endif // QT_CONFIG(shortcut)
        self.cropAction.setText(QCoreApplication.translate("ModelViewerUI", u"Crop to Selection", None))
#if QT_CONFIG(shortcut)
        self.cropAction.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+S", None))
#endif // QT_CONFIG(shortcut)
        self.resetCropAction.setText(QCoreApplication.translate("ModelViewerUI", u"Reset Crop", None))
#if QT_CONFIG(shortcut)
        self.resetCropAction.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+Shift+K", None))
#endif // QT_CONFIG(shortcut)
        self.detectFishAction.setText(QCoreApplication.translate("ModelViewerUI", u"Detect Fish (AI)", None))
#if QT_CONFIG(shortcut)
        self.detectFishAction.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+D", None))
#endif // QT_CONFIG(shortcut)
        self.imageLabel.setStyleSheet(QCoreApplication.translate("ModelViewerUI", u"background-color: gray;", None))
        self.imageLabel.setText(QCoreApplication.translate("ModelViewerUI", u"Open Folder...", None))
        self.modelGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Model", None))
#if QT_CONFIG(tooltip)
        self.nmsLabel.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The Non-Maximum Suppression threshold for the bounding boxes", None))
#endif // QT_CONFIG(tooltip)
        self.nmsLabel.setText(QCoreApplication.translate("ModelViewerUI", u"NMS", None))
#if QT_CONFIG(tooltip)
        self.confidenceSlider.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The confidence threshold for filtering detections", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.nmsSlider.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The Non-Maximum Suppression threshold for the bounding boxes", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.confidenceLabel.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The confidence threshold for filtering detections", None))
#endif // QT_CONFIG(tooltip)
        self.confidenceLabel.setText(QCoreApplication.translate("ModelViewerUI", u"Confidence", None))
#if QT_CONFIG(tooltip)
        self.detectionsLabel.setToolTip(QCoreApplication.translate("ModelViewerUI", u"Amount of object detections in the current image", None))
#endif // QT_CONFIG(tooltip)
        self.detectionsLabel.setText(QCoreApplication.translate("ModelViewerUI", u"Detections:", None))
        self.numDetectionsLabel.setText(QCoreApplication.translate("ModelViewerUI", u"0", None))
        self.imageInfoGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Image", None))
        self.imageInfoLabel.setText(QCoreApplication.translate("ModelViewerUI", u"-", None))
        self.imageExifGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Exif", None))
        self.menuFile.setTitle(QCoreApplication.translate("ModelViewerUI", u"File", None))
        self.menuEdit.setTitle(QCoreApplication.translate("ModelViewerUI", u"Edit", None))
    # retranslateUi

